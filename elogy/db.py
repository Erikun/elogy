from datetime import datetime, timedelta
from html.parser import HTMLParser
import logging

from flask import url_for
from playhouse.sqlite_ext import SqliteExtDatabase, JSONField
from peewee import (CharField, TextField, BooleanField,
                    DateTimeField, ForeignKeyField)
from peewee import Model, DoesNotExist, DeferredRelation, fn


# defer the actual db setup to later, when we have read the config
db = SqliteExtDatabase(None)


def setup_database(db_name, close=True):
    "Configure the database and make sure all the tables exist"
    # TODO: support further configuration options, see FlaskDB
    db.init(db_name)
    Logbook.create_table(fail_silently=True)
    LogbookChange.create_table(fail_silently=True)
    Entry.create_table(fail_silently=True)
    EntryChange.create_table(fail_silently=True)
    EntryLock.create_table(fail_silently=True)
    Attachment.create_table(fail_silently=True)
    if close:
        db.close()  # important


class Logbook(Model):

    """
    A logbook is a collection of entries, and (possibly) other logbooks.
    """

    class Meta:
        database = db

    created_at = DateTimeField(default=datetime.utcnow)
    last_changed_at = DateTimeField(null=True)
    name = CharField()
    description = TextField(null=True)
    template = TextField(null=True)
    template_content_type = CharField(default="text/html; charset=UTF-8")
    parent = ForeignKeyField("self", null=True, related_name="children")
    attributes = JSONField(default=[])
    metadata = JSONField(default={})
    archived = BooleanField(default=False)

    def get_entries(self, **kwargs):

        "Convenient way to query for entries in this logbook"
        return Entry.search(logbook=self, **kwargs)

    @property
    def ancestors(self):
        "The list of parent, grandparent, ..."
        parents = []
        # TODO: maybe this can be done with a recursive query?
        if self.parent:
            parent = Logbook.get(Logbook == self.parent)
            while True:
                parents.append(parent)
                try:
                    parent = Logbook.get(Logbook == parent.parent)
                except DoesNotExist:
                    break
        return list(reversed(parents))

    def make_change(self, **values):
        "Change the logbook, storing the old values as a revision"
        original_values = {
            attr: getattr(self, attr)
            for attr, value in values.items()
            if getattr(self, attr) != value
        }
        change = LogbookChange.create(logbook=self, changed=original_values)
        for attr, value in values.items():
            setattr(self, attr, value)
        self.last_changed_at = change.timestamp
        return change

    @property
    def revision_n(self):
        return len(self.changes)

    def get_revision(self, version):
        if version == self.revision_n:
            return self
        if 0 <= version < self.revision_n:
            return LogbookRevision(self.changes[version])
        raise(LogbookChange.DoesNotExist)

        # changes = (LogbookChange.select()
        #            .where(LogbookChange.logbook == self)
        #            .order_by(LogbookChange.id)
        #            .offset(version or None))
        # if changes.count() == 0:
        #     raise(LogbookChange.DoesNotExist)
        # return LogbookRevision(list(changes)[0])

    @property
    def entry_histogram(self):
        data = (Entry.select(fn.date(Entry.created_at).alias("date"),
                             fn.min(Entry.id).alias("id"),
                             fn.count(Entry.id).alias("count"))
                .group_by(fn.date(Entry.created_at))
                .order_by(fn.date(Entry.created_at)))
        return [(e.date.timestamp(), e.id, e.count) for e in data]

    def convert_attribute(self, name, value):
        "Try to convert an attribute value to the format the logbook expects"
        # Mainly useful when the logbook configuration may have changed, and
        # trying to access attributes of previously created entries.
        # Not much point in converting them until someone edits the entry.
        # Note: does not exert itself to convert values and will raise
        # ValueError if it fails.
        try:
            for info in self.attributes:
                if info["name"] == name:
                    break
            else:
                raise KeyError("Unknown attribute %s!" % name)
            if value is None and not info.get("required"):
                # ignore unset values if not required
                return
            if info["type"] == "text":
                return str(value)
            if info["type"] == "number":
                return float(value)
            elif info["type"] == "boolean":
                # Hmm... this will almost always be True
                return bool(value)
            elif info["type"] == "text" and isinstance(value, list):
                return value[0]
            elif info["type"] == "multioption" and isinstance(value, str):
                return [value]
        except (ValueError, KeyError, IndexError) as e:
            raise ValueError(e)
        return value

    def get_form_attributes(self, formdata):
        result = {}
        for attribute in self.attributes or []:
            formitem = "attribute-{name}".format(**attribute)
            if attribute["type"] == "multioption":
                # In this case we'll get the data as a list of strings
                value = formdata.getlist(formitem)
            else:
                # in all other cases as a single value
                value = formdata.get(formitem)
            if value:
                result[attribute["name"]] = self.convert_attribute(
                    attribute, value)
        return result


class LogbookChange(Model):

    class Meta:
        database = db

    logbook = ForeignKeyField(Logbook, related_name="changes")

    changed = JSONField()

    timestamp = DateTimeField(default=datetime.utcnow)
    change_authors = JSONField(null=True)
    change_comment = TextField(null=True)
    change_ip = CharField(null=True)

    def get_old_value(self, attr):

        """Get the value of the attribute at the time of this revision.
        That is, *before* the change happened."""

        # First check if the attribute was changed in this revision,
        # in that case we return that.
        if attr in self.changed:
            return self.changed[attr]
        # Otherwise, check for the next revision where this attribute
        # changed; the value from there must be the current value
        # at this revision.
        try:
            change = (LogbookChange.select()
                      .where((LogbookChange.logbook == self.logbook) &
                             (LogbookChange.changed.extract(attr) != None) &
                             (LogbookChange.id > self.id))
                      .order_by(LogbookChange.id)
                      .get())
            return change.changed[attr]
        except DoesNotExist:
            # No later revisions changed the attribute either, so we can just
            # take the value from the current logbook
            return getattr(self.logbook, attr)

    def get_new_value(self, attr):

        """Get the value of the attribute at the time of this revision.
        That is, *before* the change happened."""

        # check for the next revision where this attribute
        # changed; the value from there must be the current value
        # at this revision.
        try:
            change = (LogbookChange.select()
                      .where((LogbookChange.logbook == self.logbook) &
                             (LogbookChange.changed.extract(attr) != None) &
                             (LogbookChange.id > self.id))
                      .order_by(LogbookChange.id)
                      .get())
            return change.changed[attr]
        except DoesNotExist:
            # No later revisions changed the attribute, so we can just
            # take the value from the current logbook
            return getattr(self.logbook, attr)


class LogbookRevision:

    """Represents a historical version of a Logbook."""

    def __init__(self, change):
        self.change = change

    def __getattr__(self, attr):
        if attr == "id":
            return self.change.logbook.id
        if attr == "revision_n":
            return list(self.change.logbook.changes).index(self.change)

        if attr in ("name", "description", "template", "attributes",
                    "archived", "parent_id"):
            return self.change.get_old_value(attr)

        return getattr(self.change.logbook, attr)


DeferredEntry = DeferredRelation()


# class EntrySearch(FTS5Model):
#     entry = ForeignKeyField(DeferredEntry)
#     content = SearchField()


class MLStripper(HTMLParser):

    def __init__(self):
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


def convert_attributes(logbook, attributes):
    converted = {}
    for name, value in attributes.items():
        try:
            converted[name] = logbook.convert_attribute(name, value)
        except ValueError:
            pass
    return converted


def escape_string(s):
    "Double single quotes for sqlite"
    return s.replace("'", "''")


class Entry(Model):

    class Meta:
        database = db
        order_by = ("created_at",)

    logbook = ForeignKeyField(Logbook, related_name="entries")
    title = CharField(null=True)
    authors = JSONField(default=[])
    content = TextField(null=True)
    content_type = CharField(default="text/html; charset=UTF-8")
    metadata = JSONField(default={})  # general
    attributes = JSONField(default={})
    created_at = DateTimeField(default=datetime.utcnow)
    last_changed_at = DateTimeField(null=True)
    follows = ForeignKeyField("self", null=True, related_name="followups")
    archived = BooleanField(default=False)

    class Locked(Exception):
        pass

    @property
    def _thread(self):
        entries = []
        if self.follows:
            entry = Entry.get(Entry.id == self.follows_id)
            while True:
                entries.append(entry)
                if entry.follows_id:
                    try:
                        entry = Entry.get(Entry.id == entry.follows_id)
                    except DoesNotExist:
                        break
                else:
                    break
        if entries:
            return entries[-1]
        return self

    @property
    def next(self):
        "Next entry (order by id)"
        try:
            return (Entry.select()
                    .where((Entry.logbook == self.logbook) &
                           (Entry.follows == None) &
                           (fn.coalesce(Entry.last_changed_at, Entry.created_at)
                            > fn.coalesce(self.last_changed_at, self.created_at)))
                    .order_by(fn.coalesce(Entry.last_changed_at, Entry.created_at))
                    .get())
        except DoesNotExist:
            pass

    @property
    def previous(self):
        "Previous entry (order by id)"
        try:
            return (Entry.select()
                    .where((Entry.logbook == self.logbook) &
                           (Entry.follows == None) &
                           (fn.coalesce(Entry.last_changed_at, Entry.created_at)
                            < fn.coalesce(self.last_changed_at, self.created_at)))
                    .order_by(fn.coalesce(Entry.last_changed_at,
                                          Entry.created_at).desc())
                    .get())
        except DoesNotExist:
            pass

    def make_change(self, **data):
        "Change the entry, storing the old values as a revision"
        original_values = {
            attr: getattr(self, attr)
            for attr, value in data.items()
            if hasattr(self, attr) and getattr(self, attr) != value
        }
        # TODO: what should we do if the new data is the same as the old?
        change = EntryChange(entry=self, changed=original_values)
        for attr in original_values:
            value = data[attr]
            setattr(self, attr, value)
        self.last_changed_at = change.timestamp
        return change

    @property
    def revision_n(self):
        return len(self.changes)

    def get_revision(self, version):
        if version == self.revision_n:
            return self
        if 0 <= version < self.revision_n:
            return EntryRevision(self.changes[version])
        raise(EntryChange.DoesNotExist)

    # def get_old_version(self, revision_id):
    #     revisions = (EntryChange.select()
    #                  .where(EntryChange.entry == self
    #                         and EntryChange.id >= revision_id)
    #                  .order_by(EntryChange.id.desc()))
    #     content = self.content
    #     print(content)
    #     print("---")
    #     for revision in revisions:
    #         print(revision.content)
    #         if revision.content:
    #             content = apply_patch(content, revision.content)
    #     return content

    @property
    def stripped_content(self):
        return strip_tags(self.content)

    def get_attachments(self, embedded=False):
        return self.attachments.filter((Attachment.embedded == embedded) &
                                       ~Attachment.archived)

    @property
    def converted_attributes(self):
        "Ensure that the attributes conform to the logbook configuration"
        return convert_attributes(self.logbook, self.attributes)

    def get_lock(self, ip=None, acquire=False, steal=False):
        """check if there's a lock on the entry, and if an ip is given
        try to acquire it."""
        try:
            lock = EntryLock.get((EntryLock.entry_id == self.id) &
                                 (EntryLock.expires_at > datetime.utcnow()) &
                                 (EntryLock.cancelled_at == None))
            if steal:
                lock.cancel(ip)
                return EntryLock.create(entry=self, owned_by_ip=ip)
            if acquire and ip != lock.owned_by_ip:
                raise self.Locked(lock)
            return lock
        except EntryLock.DoesNotExist:
            if acquire:
                return EntryLock.create(entry=self, owned_by_ip=ip)

    @property
    def lock(self):
        return self.get_lock()

    @classmethod
    def search(cls, logbook=None, followups=False,
               child_logbooks=False, archived=False,
               n=None, offset=0, count=False,
               attribute_filter=None, content_filter=None,
               title_filter=None, author_filter=None,
               attachment_filter=None):

        # Note: this is all pretty messy. The reason we're building
        # the query as a raw string is that peewee does not (currently)
        # support recursive queries, which we need in order to search
        # through nested logbooks. Cleanup needed!

        if attribute_filter:
            # need to extract the attribute values from JSON here, so that
            # we can match on them later
            attributes = ", {}".format(
                ", ".join(
                    "json_extract(entry.attributes, '$.{attr}') AS {attr_id}"
                    .format(attr=escape_string(attr),
                            attr_id="attr{}".format(i))
                    for i, (attr, _) in enumerate(attribute_filter)))
        else:
            attributes = ""

        if author_filter:
            # extract the author names as a separate table, so that
            # they can be searched
            # TODO: maybe also take login?
            authors = ", json_each(entry.authors) AS authors2"
        else:
            authors = ""

        if logbook:
            if child_logbooks:
                # recursive query to find all entries in the given logbook
                # or any of its descendants, to arbitrary depth
                query = """
WITH recursive logbook1(id,parent_id) AS (
    values({logbook}, NULL)
    UNION ALL
    SELECT logbook.id, logbook.parent_id FROM logbook,logbook1
    WHERE logbook.parent_id=logbook1.id
)
SELECT {what}{attributes},
       {attachment}
       coalesce(followup.follows_id, entry.id) AS thread,
       count(followup.id) AS n_followups,
       max(datetime(coalesce(coalesce(followup.last_changed_at,followup.created_at),
                             coalesce(entry.last_changed_at,entry.created_at)))) AS timestamp
FROM entry{authors}
JOIN logbook1
{join_attachment}
LEFT JOIN entry AS followup ON entry.id == followup.follows_id
WHERE entry.logbook_id=logbook1.id
""".format(attributes=attributes,
           attachment=("path as attachment_path," if attachment_filter else ""),
           what="COUNT(distinct(coalesce(followup.follows_id, entry.id))) AS count" if count else "entry.*",
           authors=authors, logbook=logbook.id,
           join_attachment=("JOIN attachment ON attachment.entry_id == entry.id" if attachment_filter else ""))
            else:
                # In this case we're not searching recursively
                query = (
                    "SELECT {what}{attributes},coalesce(entry.last_changed_at, entry.created_at) AS timestamp FROM entry{authors} WHERE entry.logbook_id = {logbook}"
                    .format(what="count()" if count else "entry.*",
                            logbook=logbook,
                            attributes=attributes,
                            authors=authors))
        else:
            # In this case we're searching all entries and don't need
            # the recursive logbook filtering
            query = """
SELECT {what}{attributes},count(followup.id) AS n_followups,
       max(datetime(coalesce(coalesce(followup.last_changed_at,followup.created_at),
                    coalesce(entry.last_changed_at,entry.created_at)))) AS timestamp
FROM entry{authors}
LEFT JOIN entry AS followup ON entry.id == followup.follows_id
WHERE 1
""".format(what="count()" if count else "entry.*",
           attributes=attributes, authors=authors)

        if not archived:
            query += " AND NOT entry.archived"

        variables = []

        # if not followups:
        #     query += " AND entry.follows_id IS NULL"

        # further filters on the results, depending on search criteria
        if content_filter:
            # need to filter out null or REGEX will explode on them
            query += " AND entry.content IS NOT NULL AND entry.content REGEXP ?"
            variables.append(content_filter)
        if title_filter:
            query += " AND entry.title IS NOT NULL AND entry.title REGEXP ?"
            variables.append(title_filter)
        if author_filter:
            query += " AND json_extract(authors2.value, '$.name') REGEXP ?"
            variables.append(author_filter)
        if attachment_filter:
            query += " AND attachment_path REGEXP ?"
            variables.append(attachment_filter)
        if attribute_filter:
            for i, (attr, value) in enumerate(attribute_filter):
                query += " AND ? = ?"
                variables.extend(["attr{}".format(i), value])

        # Here we're getting into deep water...
        # If we just want the total count of results, we can't group
        # because then the count would be per group. So that makes sense.
        # However, when we're searching, we also don't want the grouping
        # because it means we won't find individual followups
        if not count:
            query += " GROUP BY entry.id"
            if not any([title_filter, content_filter, author_filter]):
                query += " HAVING entry.follows_id IS NULL"
        # sort newest first, taking into account the last edit if any
        # TODO: does this make sense? Should we only consider creation date?
        query += " ORDER BY timestamp DESC"
        if n:
            query += " LIMIT {}".format(n)
            if offset:
                query += " OFFSET {}".format(offset)
        logging.debug("{}, variables={}", query, ", ".join(variables))
        return Entry.raw(query, *variables)


DeferredEntry.set_model(Entry)


class EntryChange(Model):

    """
    Represents a change of an entry.

    The nomenclature here is that a *revision* is what an entry looked
    like at at a given point in time, while a change happens at a
    specific time and takes us from one revision to the next.

    Counter-intuitively, what's stored here is the *old* entry
    data. The point is that then we only need to store the fields that
    actually were changed! But it becomes a bit confusing when it's
    time to reconstruct an old entry.
    """

    class Meta:
        database = db

    entry = ForeignKeyField(Entry, related_name="changes")

    changed = JSONField()

    timestamp = DateTimeField(default=datetime.utcnow)
    change_authors = JSONField(null=True)
    change_comment = TextField(null=True)
    change_ip = CharField(null=True)

    def get_old_value(self, attr):

        """Get the value of the attribute at the time of this revision.
        That is, *before* the change happened."""

        # First check if the attribute was changed in this revision,
        # in that case we return the stored value.
        if attr in self.changed:
            return self.changed[attr]
        # Otherwise, check for the next revision where this attribute
        # changed; the value from there must be the current value
        # at this revision.
        try:
            change = (EntryChange.select()
                      .where((EntryChange.entry == self.entry) &
                             (EntryChange.changed.extract(attr) != None) &
                             (EntryChange.id > self.id))
                      .order_by(EntryChange.id)
                      .get())
            return change.changed[attr]
        except DoesNotExist:
            # No later revisions changed the attribute either, so we can just
            # take the value from the entry
            return getattr(self.entry, attr)

    def get_new_value(self, attr):

        """Get the value of the attribute after this revision happened.
        If it was not changed, it'll just be the same as before."""

        # Check for the next revision where this attribute changed;
        # the value from there must also be the value after this
        # revision.
        try:
            change = (EntryChange.select()
                        .where((EntryChange.entry == self.entry) &
                               (EntryChange.changed.extract(attr) != None) &
                               (EntryChange.id > self.id))
                        .order_by(EntryChange.id)
                        .get())
            return change.changed[attr]
        except DoesNotExist:
            # No later revisions changed the attribute, so we can just
            # take the value from the entry
            return getattr(self.entry, attr)


class EntryRevision:

    """An object that represents a historical version of an entry. It
    can (basically) be used like an Entry object."""

    def __init__(self, change):
        self.change = change

    def __getattr__(self, attr):
        if attr == "id":
            return self.change.entry.id
        if attr == "revision_n":
            return list(self.change.entry.changes).index(self.change)
        if attr in ("logbook", "title", "authors", "content", "attributes",
                    "metadata", "follows_id", "tags", "archived"):
            return self.change.get_old_value(attr)
        if attr == "converted_attributes":
            return convert_attributes(self.change.entry.logbook,
                                      self.change.get_old_value("attributes"))
        return getattr(self.change.entry, attr)


class EntryLock(Model):
    """Contains temporary edit locks, to prevent overwriting changes.
    An entry can not have more than one lock active at any given time.

    The logic of entry locks works like this:

    - user A wants to edit entry 1.
    - before starting, A acquires a lock on entry 1; lock1A.
    - soon, user B wants to edit entry 1.
    - B tries to acquire a lock on 1, but can't since A already has it.
    - B is prevented from unknowingly conflicting with A!
    - B can now either:
       + wait for A to submit his/her edits and then try again,
       + wait for the lock to expire (which it will, in, say 1h)
       + "steal" the lock.
    - If B steals the lock it means that A no longer has the lock, and
      might be in for a nasty surprise when he/she tries to submit later.
    - When submitting an edit, it's necessary to include the
      "last_changed_at" field of the version that was edited. This
      way, the server can check if the entry has been changed meanwhile.
      If this is not the case, and nobody else has locked the entry, it's
      allowed. Note that it does not matter if the lock has expired. It's
      not necessary to acquire a lock to do an edit, it's just polite.
    - B might know that A is no longer interested in the edit, so it makes
      sense to make the option of stealing available, as long as it's
      explicit.
    - When the owner of a lock submits changes to the locked entry, the
      lock is automatically cancelled.
    - The owher of a lock can also choose to cancel it without writing the
      entry. Otherwise it will also expire after a while.

    The point of locking is to make it harder for users to overwrite
    each others changes *by mistake*, not to make it impossible.

    """

    class Meta:
        database = db

    entry = ForeignKeyField(Entry)
    created_at = DateTimeField(default=datetime.utcnow)
    expires_at = DateTimeField(default=(lambda: datetime.utcnow() +
                                        timedelta(hours=1)))
    owned_by_ip = CharField()
    cancelled_at = DateTimeField(null=True)
    cancelled_by_ip = CharField(null=True)

    @property
    def locked(self):
        return not self.cancelled_at and self.expires_at > datetime.utcnow()

    def cancel(self, ip):
        self.cancelled_at = datetime.utcnow()
        self.cancelled_by_ip = ip
        self.save()


class Attachment(Model):
    """Store information about an attachment, e.g. an arbitrary file
    associated with an entry. The file itself is not stored in the
    database though, only a path to where it's expected to be.
    """

    class Meta:
        database = db
        order_by = ("id",)

    entry = ForeignKeyField(Entry, null=True, related_name="attachments")
    filename = CharField(null=True)
    timestamp = DateTimeField(default=datetime.utcnow)
    path = CharField()  # path within the upload folder
    content_type = CharField(null=True)
    embedded = BooleanField(default=False)  # i.e. an image in the content
    metadata = JSONField(null=True)  # may contain image size, etc
    archived = BooleanField(default=False)

    @property
    def link(self):
        return url_for("get_attachment", path=self.path)

    @property
    def thumbnail_link(self):
        return url_for("get_attachment", path=self.path) + ".thumbnail"
