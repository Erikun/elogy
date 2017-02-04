from base64 import decodestring
from datetime import datetime
import io
import json
import os

from jinja2 import TemplateNotFound
from dateutil.parser import parse
from flask import (Blueprint, abort, redirect, render_template, request,
                   url_for)
from werkzeug import FileStorage
from peewee import JOIN, fn, DoesNotExist
from lxml import html, etree

from .attachments import save_attachment
from .db import Entry, Logbook, EntryLock, Attachment


entries = Blueprint('entries', __name__)


@entries.route("/<int:entry_id>")
def show_entry(entry_id):
    "Display an entry"
    entry = Entry.get(Entry.id == entry_id)
    return render_template("entry.jinja2", entry=entry, **request.args)


@entries.route("/new")
def new_entry():
    "Deliver a form for posting a new entry"
    data = request.args
    follows_id = int(data.get("follows", 0))
    if follows_id:
        follows = Entry.get(Entry.id == follows_id)
        logbook = follows.logbook
    else:
        follows = None
        logbook_id = int(data["logbook"])
        logbook = Logbook.get(Logbook.id == logbook_id)
    return render_template('edit_entry.jinja2',
                           logbook=logbook, follows=follows)


@entries.route("/edit/<int:entry_id>")
def edit_entry(entry_id):

    "Deliver a form for editing an existing entry"

    entry = Entry.get(Entry.id == entry_id)

    # we use a simple table to store temporary "locks" on entries that
    # are being edited.  The idea is to prevent collisions where one
    # user saves over the edits of another. Note that since all
    # changes are stored, we should never actually *lose* data, but it
    # can still be annoying.
    try:
        lock = EntryLock.get(EntryLock.entry == entry)
        return render_template("entry_lock.jinja2", lock=lock)
    except DoesNotExist:
        lock = EntryLock.create(entry=entry, owner_ip=request.remote_addr)

    if entry.follows:
        follows = Entry.get(Entry.id == entry.follows)
    else:
        follows = 0
    logbook = entry.logbook
    return render_template('edit_entry.jinja2',
                           entry=entry, logbook=logbook, follows=follows)


def handle_img_tags(text, entry_id=None, timestamp=None):
    """Get image tags from the text. Extract embedded images and save
    them as attachments"""
    attachments = []
    timestamp = timestamp or datetime.now()
    try:
        doc = html.document_fromstring(text)
    except etree.ParserError:
        return text, attachments
    for i, element in enumerate(doc.xpath("//*[@src]")):
        src = element.attrib['src'].split("?", 1)[0]
        if src.startswith("data:"):
            header, data = src[5:].split(",", 1)  # TODO: find a safer way
            filetype, encoding = header.split(";")
            raw_image = decodestring(data.encode("ascii"))
            try:
                # TODO: possible to be more clever about the filename?
                filename = "decoded-{}-{}.{}".format(
                    len(raw_image), i, filetype.split("/")[1].lower())
            except IndexError:
                print("weird filetype!?", filetype)
                continue
            file_ = FileStorage(io.BytesIO(raw_image),
                                filename=filename, content_type=filetype)
            attachment = save_attachment(file_, timestamp, entry_id)
            src = element.attrib["src"] = os.path.join(
                url_for("attachments.get_attachment", filename=""),
                attachment.path)
            if element.getparent().tag == "a":
                element.getparent().attrib["href"] = src

        attachments.append(src)
    return html.tostring(doc), attachments


def remove_lock(entry_id):
    lock = EntryLock.get(EntryLock.entry_id == entry_id)
    lock.delete_instance()


@entries.route("/unlock/<int:entry_id>")
def unlock_entry(entry_id):
    "Remove the lock on the given entry"
    remove_lock(entry_id)
    return redirect(url_for(".show_entry", entry_id=entry_id))


@entries.route("/", methods=["POST"])
@entries.route("/<int:entry_id>", methods=["POST"])
def write_entry(entry_id=None):

    "Save a submitted entry (new or edited)"

    data = request.form

    logbook_id = int(data["logbook"])
    logbook = Logbook.get(Logbook.id == logbook_id)

    # a list of attachment filenames
    attachments = data.getlist("attachment")
    print("attachments", attachments)
    # for att in attachments:
    #     if

    # Pick up attributes
    attributes = {}
    for attr in logbook.attributes or []:
        value = data.get("attribute-{}".format(attr["name"]))
        if value:
            # since we always get strings from the form, we need to
            # convert the values to proper types
            attributes[attr["name"]] = logbook.convert_attribute(
                attr["name"], value)

    # Make a list of authors
    authors = [author.strip()
               for author in data.getlist("author")
               if author]

    if entry_id:
        # editing an existing entry, first check for locks
        try:
            lock = EntryLock.get(EntryLock.entry_id == entry_id)
            if lock.owner_ip == request.remote_addr:
                # it's our lock
                lock.delete_instance()
            else:
                unlock = int(data.get("unlock", 0))
                if lock.entry_id == unlock:
                    # the user has decided to unlock the entry and save anyway
                    remove_lock(lock.entry_id)
                else:
                    # locked by someone else, let's send everyting back
                    # with a warning.
                    entry = Entry(id=entry_id,
                                  title=data.get("title"),
                                  authors=authors,
                                  content=data.get("content"),
                                  follows=int(data.get("follows", 0)) or None,
                                  attributes=attributes,
                                  archived="archived" in data,
                                  attachments=attachments,
                                  logbook=logbook)
                    return render_template("edit_entry.jinja2",
                                           entry=entry, lock=lock)
        except DoesNotExist as e:
            # Note: there should be a lock, but maybe someone removed it.
            # In this case, not much to do..?
            pass

        # Now make the change
        entry = Entry.get(Entry.id == entry_id)
        change = entry.make_change(title=data.get("title"),
                                   content=data.get("content"),
                                   authors=authors,
                                   attributes=attributes,
                                   attachments=attachments)
        change.save()

    else:
        # creating a new entry
        if "created_at" in data:
            created_at = parse(data.get("created_at"))
        else:
            created_at = datetime.now()

        entry = Entry(title=data.get("title"),
                      authors=authors,
                      created_at=created_at,
                      content=data.get("content"),
                      follows=int(data.get("follows", 0)) or None,
                      attributes=attributes,
                      archived="archived" in data,
                      attachments=attachments,
                      logbook=logbook)

    entry.save()

    try:
        # Grab all image elements from the HTML.
        # TODO: this will explode on data URIs, those should
        # be ignored. Also we need to ignore links to external images.
        content, embedded_attachments = handle_img_tags(
            entry.content, entry_id)
        entry.content = content
        entry.save()
        for url in embedded_attachments:
            path = url[1:].split("/", 1)[-1]
            try:
                attachment = Attachment.get(Attachment.path == path)
                attachment.entry_id = entry.id
                attachment.save()
            except DoesNotExist:
                print("Did not find attachment", url)
    except SyntaxError as e:
        print(e)

    follows = int(data.get("follows", 0))
    if follows:
        return redirect("/entries/{}#{}".format(follows, entry.id))
    return redirect("/entries/{}".format(entry.id))
