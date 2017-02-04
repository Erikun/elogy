from base64 import decodestring
from datetime import datetime
import io
import json
from jinja2 import TemplateNotFound

from bs4 import BeautifulSoup
from .db import Entry, Logbook
from flask import (Blueprint, abort, redirect, render_template, request,
                   url_for)
from werkzeug import FileStorage
from peewee import JOIN, fn, DoesNotExist
from lxml import html

from .attachments import save_attachment
from .db import EntryLock


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


def handle_img_tags(text, timestamp):
    """Get image tags from the text. Extract embedded images and save
    them as attachments"""
    # TODO: This is the only thing we need BS for. Use lxml instead.
    # tree = html.document_fromstring(text)
    # attachments = tree.xpath('//img/@src')
    # ...
    soup = BeautifulSoup(text)
    attachments = []
    for img in soup.findAll('img'):
        src = img['src']
        if src.startswith("data:"):
            header, data = src[5:].split(",", 1)  # TODO: find a safer way
            filetype, encoding = header.split(";")
            try:
                # TODO: possible to be more clever about the filename?
                filename = "decoded." + filetype.split("/")[1].lower()
            except IndexError:
                print("weird filetype!?", filetype)
                continue
            file_ = FileStorage(io.BytesIO(decodestring(data.encode("ascii"))),
                                filename=filename)
            src = img["src"] = save_attachment(file_, timestamp)
        attachments.append(src)
    return str(soup), attachments


def remove_lock(entry_id):
    lock = EntryLock.get(EntryLock.entry_id == entry_id)
    lock.delete_instance()


@entries.route("/unlock/<int:entry_id>")
def unlock_entry(entry_id):
    "Remove the lock on the given entry"
    remove_lock(entry_id)
    return redirect(url_for(".show_entry", entry_id=entry_id))


@entries.route("/<int:entry_id>", methods=["POST"])
def write_entry(entry_id):

    "Save a submitted entry (new or edited)"

    data = request.form

    logbook_id = int(data["logbook"])
    logbook = Logbook.get(Logbook.id == logbook_id)

    # a list of attachment filenames
    attachments = data.getlist("attachment")
    try:
        # Grab all image elements from the HTML.
        # TODO: this will explode on data URIs, those should
        # be ignored. Also we need to ignore links to external images.
        content, image_attachments = handle_img_tags(data.get("content"),
                                                     datetime.now())
        attachments.append(image_attachments)
    except SyntaxError as e:
        #
        print(e)
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
                                  title=data["title"],
                                  authors=authors,
                                  content=data["content"],
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
        change = entry.make_change({
            "title": data["title"],
            "content": data["content"],
            "authors": authors,
            "attributes": attributes,
            "attachments": attachments
        })
        change.save()
        entry.save()

    else:
        # creating a new entry
        entry = Entry(title=data["title"],
                      authors=authors,
                      content=data["content"],
                      follows=int(data.get("follows", 0)) or None,
                      attributes=attributes,
                      archived="archived" in data,
                      attachments=attachments,
                      logbook=logbook)

        entry.save()

    follows = int(data.get("follows", 0))
    if follows:
        return redirect("/entries/{}#{}".format(follows, entry.id))
    return redirect("/entries/{}".format(entry.id))
