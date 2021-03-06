import base64
import json
import os
import re
import sqlite3
from argparse import ArgumentParser
from random import randint
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


parser = ArgumentParser(description="Convert an AnkiApp database to true Anki decks")
parser.add_argument(
    "-d", "--database", help="AnkiApp database file", required=False, default=None
)
parser.add_argument("-o", "--output", help="Output directory", required=False, default="output")
args = parser.parse_args()

db_path = args.database
if not db_path:
    if os.name == "nt":
        db_path = f"{os.environ['APPDATA']}/AnkiApp/databases/file_0/1"
    else:
        print(
            "Unable to determine path to AnkiApp database. Please specify it manually with the --database flag."
        )
        exit(-1)

os.mkdir(args.output)

with TemporaryDirectory() as tmpdir, sqlite3.connect(db_path) as conn:
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
        package.write_to_file(
            os.path.join(
                args.output, "{}.apkg".format(deck_data["name"].replace("/", "-"))
            )
        )
    print("{} decks exported to {}".format(len(decks), os.path.realpath(args.output)))
