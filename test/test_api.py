import json

from .fixtures import elogy_client


def decode_response(response):
    return json.loads(response.get_data().decode("utf-8"))


def make_logbook(client):
    in_logbook = dict(
        name="Test logbook",
        description="Test description")
    return in_logbook, decode_response(
        client.post("/api/logbooks/", data=in_logbook))


def make_entry(client, logbook):

    in_entry = dict(
        title="Test entry",
        content="This is some test content!",
        content_type="text/plain")

    response = decode_response(
        client.post(
            "/api/logbooks/{logbook[id]}/entries/".format(logbook=logbook),
            data=in_entry))

    return in_entry, response


def test_create_logbook(elogy_client):

    in_logbook, logbook = make_logbook(elogy_client)

    # read it back
    out_logbook = decode_response(
        elogy_client.get("/api/logbooks/{logbook[id]}/"
                         .format(logbook=logbook)))

    assert in_logbook["name"] == out_logbook["name"]
    assert in_logbook["description"] == out_logbook["description"]


def test_update_logbook(elogy_client):
    in_logbook, logbook = make_logbook(elogy_client)

    # read it back
    out_logbook = decode_response(
        elogy_client.get("/api/logbooks/{logbook[id]}/"
                         .format(logbook=logbook)))

    response = decode_response(
        elogy_client.put("/api/logbooks/{}/".format(out_logbook["id"]),
                         data=dict(name="New name",
                                   description=out_logbook["description"])))


def test_create_entry(elogy_client):
    in_logbook, logbook = make_logbook(elogy_client)
    in_entry, entry = make_entry(elogy_client, logbook)

    # read the entry back
    out_entry = decode_response(
        elogy_client.get("/api/logbooks/{logbook[id]}/entries/{entry[id]}/"
                         .format(logbook=logbook, entry=entry)))

    assert out_entry["title"] == in_entry["title"]
    assert out_entry["content"] == in_entry["content"]
    assert out_entry["id"] == entry["id"]


def test_update_entry(elogy_client):
    in_logbook, logbook = make_logbook(elogy_client)
    in_entry, entry = make_entry(elogy_client, logbook)

    # change the title
    new_in_entry = {**in_entry, "title": "New title"}
    response = decode_response(
        elogy_client.put("/api/logbooks/{logbook[id]}/entries/{entry[id]}/"
                         .format(logbook=logbook, entry=entry),
                         data=new_in_entry))

    # verify that the change has had effect
    out_entry = decode_response(
        elogy_client.get("/api/logbooks/{logbook[id]}/entries/{entry[id]}/"
                         .format(logbook=logbook, entry=entry)))

    assert out_entry["title"] == new_in_entry["title"]
    assert out_entry["content"] == new_in_entry["content"]
    assert out_entry["id"] == entry["id"]


def test_lock_entry(elogy_client):

    in_logbook, logbook = make_logbook(elogy_client)
    in_entry, entry = make_entry(elogy_client, logbook)

    IP = '1.2.3.4'
    print(logbook, entry)
    lock = decode_response(
        elogy_client.post(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry),
            environ_base={'REMOTE_ADDR': IP}))

    assert lock["owned_by_ip"] == IP

    # verify that the entry is locked
    get_lock = decode_response(
        elogy_client.get(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry)))
    assert get_lock["id"] == lock["id"]

    # acquire the lock again from the same host
    lock_again = decode_response(
        elogy_client.post(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry),
            environ_base={'REMOTE_ADDR': IP}))

    # should be the same lock
    assert lock_again["id"] == lock["id"]

    # try to change the entry from the same host
    edit_entry = elogy_client.put(
        "/api/logbooks/{logbook[id]}/entries/{entry[id]}/"
        .format(logbook=logbook, entry=entry),
        data=dict(title="New title"),
        environ_base={'REMOTE_ADDR': IP})
    assert edit_entry.status_code == 200

    # verify that the entry is no longer locked
    no_lock = elogy_client.get(
        "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
        .format(logbook=logbook, entry=entry))
    assert no_lock.status_code == 404


def test_lock_entry_conflict(elogy_client):

    in_logbook, logbook = make_logbook(elogy_client)
    in_entry, entry = make_entry(elogy_client, logbook)

    IP = '1.2.3.4'

    lock = decode_response(
        elogy_client.post(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry),
            environ_base={'REMOTE_ADDR': IP}))

    # attempt to acquire a lock from another host
    OTHER_IP = '5.6.7.8'
    other_lock = elogy_client.post(
        "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
        .format(logbook=logbook, entry=entry),
        environ_base={'REMOTE_ADDR': OTHER_IP})

    # it should fail with a conflict
    assert other_lock.status_code == 409

    # try to change the entry from another host
    other_edit_entry = elogy_client.put(
        "/api/logbooks/{logbook[id]}/entries/{entry[id]}/"
        .format(logbook=logbook, entry=entry),
        data=dict(title="New title"),
        environ_base={'REMOTE_ADDR': OTHER_IP})

    assert other_edit_entry.status_code == 409

    # now cancel the lock
    cancelled_lock = decode_response(
        elogy_client.delete(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry),
            data={"lock_id": lock["id"]}))
    assert cancelled_lock["cancelled_at"] is not None

    # acquire the lock from the other host
    other_lock2 = decode_response(
        elogy_client.post(
            "/api/logbooks/{logbook[id]}/entries/{entry[id]}/lock"
            .format(logbook=logbook, entry=entry),
            environ_base={'REMOTE_ADDR': OTHER_IP}))
    assert other_lock2["owned_by_ip"] == OTHER_IP
