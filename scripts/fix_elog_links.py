"""
After an import with "import_elog.py", run this script to find old
ELOG links in the database and convert them to new URLs. It also
finds image links to attachments and updates them to point to the new
URLs.

The script assumes that the entries have been imported using
"import_elog.py" since it requires some metadata to be stored
for entries and attachments. It can't fix entries that have been
created in other ways.

Operates directly on the sqlite DB file, so back it up before trying.

Usage:

$ python fix_elog_links.py elogy.db host.of.old.elog other.address.to/elog

"""

import os
import re

from lxml import html, etree
from urllib.parse import unquote_plus, quote


def update_bad_links(db, url):
    """
    Update links to other entries in the old ELOG installation to point to the
    correct entry in the new database
    """
    QUERY = "SELECT id, content FROM entry WHERE content LIKE ?"
    for entry_id, content in db.execute_sql(QUERY, ["%{}%".format(url)]):
        print("=" * 40)
        print("entry ID:", entry_id)
        doc = html.document_fromstring(content)
        for element in doc.xpath("//*[@href]"):
            print(element.attrib["href"])
            results = re.search(os.path.join(url, '(.*)'),
                                element.attrib["href"])
            if results:
                elog_url, = results.groups()
                print("elog_url", elog_url)
                rows = db.execute_sql("SELECT id, logbook_id FROM entry WHERE json_extract(entry.metadata, '$.original_elog_url') = ?", [elog_url])
                result = rows.fetchone()
                if result:
                    linked_entry_id, logbook_id = result
                    old_url = str(element.attrib["href"])
                    new_url = "/logbooks/{}/entries/{}/".format(logbook_id,
                                                                linked_entry_id)
                    print("\t", old_url, new_url)
                    db.execute_sql(
                        "UPDATE entry SET content = replace(content, ?, ?) WHERE id = ?",
                        [old_url, new_url, entry_id])
                else:
                    print("Sorry, could not find new url!")


def update_attachment_links(db):

    # elog entries can contain <img> elements that point directly to
    # attachments.
    # E.g. 170128_075052/Archiverprobs.PNG?lb=Accelerator+Issues
    # This function finds such links and tries to uodate them

    # Find all entries that contain at least one "old style" attachment link
    ATTACHMENT_LINK_URL = '(\d{6}_\d{6}/[^\?]*)\?lb=([^"&]+)'
    QUERY = "SELECT id, content FROM entry WHERE content REGEXP ?"
    print(QUERY, ATTACHMENT_LINK_URL)
    for entry_id, content in db.execute_sql(QUERY, ['src="'+ATTACHMENT_LINK_URL]):
        print("=" * 40)
        print("entry ID:", entry_id)
        path, logbook = re.search(ATTACHMENT_LINK_URL, content).groups()
        # OK, now go through the content and locate all problematic src fields
        doc = html.document_fromstring(content)
        for element in doc.xpath("//*[@src]"):
            results = re.search(ATTACHMENT_LINK_URL, element.attrib["src"])
            if results:
                path, logbook = results.groups()
                filename = path.replace("/", "_")  # no idea why elog does this
                filename = unquote_plus(filename)  # links are URL quoted
                logbook_name = unquote_plus(logbook)  # names with spaces need decoding
                print("Found:", filename, logbook_name)
                attachment_id = db.execute_sql("SELECT id, path FROM attachment where json_extract(metadata, '$.original_elog_filename') = ?", [filename])
                if not attachment_id:
                    print("No attachment found; maybe it was not imported properly.")
                    continue
                for att_id, att_filename in attachment_id:
                    old = results.group(0)
                    new = "/attachments/{}".format(att_filename)  # new URL
                    print("\tReplacing:", old, new)
                    quoted_url = quote(new)
                    element.attrib["src"] = quoted_url  # replace the src attribute
                    if element.getparent().tag == "a":
                        # if the pareht element is a link, we'll
                        # assume it should also go to the attachment.
                        element.getparent().attrib["href"] = quoted_url
        # now write the updated content to the database
        new_content = etree.tostring(doc).decode("utf-8")
        db.execute_sql("UPDATE entry SET content = ? WHERE id = ?",
                       [new_content, entry_id])


if __name__ == "__main__":

    import sys
    from playhouse.sqlite_ext import SqliteExtDatabase

    # List of base URLs to look for, should be the base address(es) that
    # the imported ELOG installation was running under.
    OLD_URLS = sys.argv[2:]

    db = SqliteExtDatabase(sys.argv[1])

    for url in OLD_URLS:
        update_bad_links(db, url)

    update_attachment_links(db)
