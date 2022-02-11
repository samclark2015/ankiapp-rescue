import base64
import json
import os
import re
import sqlite3
from itertools import groupby
from operator import mod
from random import randint, random
from tempfile import TemporaryDirectory

import genanki as anki

BLOB_RE = r"{{blob ([^}]*)}}"


def blob_to_html(string):
    return re.sub(BLOB_RE, "<img src='\\1' />", string)


def dump_blobs(curs: sqlite3.Cursor, base, sub_q: str):
    q = "select * from knol_blobs where knol_value_id in ({})".format(sub_q)
    rows = curs.execute(q).fetchall()
    files = []
    for i, blob in enumerate(rows):
        # ext = mimetypes.guess_extension(blob["type"])
        path = os.path.join(base, blob["id"])
        with open(path, "wb") as f:
            data = base64.b64decode(blob["value"])
            f.write(data)
        files.append(os.path.abspath(path))
    return files


with TemporaryDirectory() as tmpdir:
    with sqlite3.connect("fake anki.sqlite3") as conn:
        conn.row_factory = sqlite3.Row
        curs = conn.cursor()

        decks = curs.execute("select id, name from decks").fetchall()
        models = {
            r["id"]: anki.Model(
                model_id=randint(1 << 30, 1 << 31),
                name=r["name"],
                fields=[
                    {"name": match, "font": "Arial"}
                    for match in set(
                        match
                        for template in json.loads(r["templates"])
                        for match in re.findall(r"\{\{\[([^\/\#\]]*)\]\}\}", template)
                        + re.findall(r"\{\{([^\/\#\[\]\}]*)\}\}", template)
                        if match
                        not in ["FrontSide", "Tags", "Type", "Deck", "Subdeck", "Card"]
                    )
                ],
                templates=[
                    {
                        "name": "Card 1",
                        "qfmt": json.loads(r["templates"])[0],
                        "afmt": json.loads(r["templates"])[1],
                    }
                ],
                css=r["style"],
            )
            for r in curs.execute(
                "select id, name, templates, style from layouts"
            ).fetchall()
        }

        print(models["a4abf3245c0340c39e43216fcd714dfc"])

        for deck_data in decks:
            deck_id = deck_data["id"]
            knol_values_q = 'select id from knol_values where knol_id in (select knol_id from cards where id in (select card_id from cards_decks where deck_id = "{}"))'.format(
                deck_id
            )
            files = dump_blobs(curs, tmpdir, knol_values_q)

            cards = curs.execute(
                "select * from cards where id in (select card_id from cards_decks where deck_id = ?)",
                (deck_id,),
            ).fetchall()

            deck = anki.Deck(randint(10_000, 10_000_000), deck_data["name"])

            for card in cards:
                # layout = curs.execute(
                #     "select name from layouts where id = ?", (card["layout_id"],)
                # ).fetchone()

                model = models[card["layout_id"]]
                valid_fields = [field["name"] for field in model.fields]

                fields = []
                for field in valid_fields:
                    knol_value = curs.execute(
                        "select knol_id, knol_key_name, value from knol_values where knol_id = ? and knol_key_name = ?",
                        (card["knol_id"], field),
                    ).fetchone()
                    fields += [blob_to_html(knol_value["value"])]
                note = anki.Note(fields=fields, model=model)
                deck.add_note(note)

            package = anki.Package(deck, files)
            package.write_to_file("{}.apkg".format(deck_data["name"].replace("/", "-")))
