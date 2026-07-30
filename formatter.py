import json

INPUT_FILE = r"C:\Users\mahee.shah\Desktop\trackproject\subdivs\matched_tracks_bnsf.json"
OUTPUT_FILE = r"C:\Users\mahee.shah\Desktop\trackproject\subdivs\location_database_bnsf.jsonl"

seen = set()

with open(INPUT_FILE, "r", encoding="utf-8") as infile, \
     open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:

    for line in infile:

        if not line.strip():
            continue

        record = json.loads(line)

        #
        # START LOCATION
        #
        if (
            record.get("start_location")
            and record.get("start_lat") is not None
            and record.get("start_lon") is not None
        ):

            key = (
                record["start_location"],
                record["scac"],
                record["subdivision_id"]
            )

            if key not in seen:

                seen.add(key)

                location_record = {
                    "location_name": record["start_location"],
                    "source": "start",
                    "scac": record["scac"],
                    "subdivision_id": record["subdivision_id"],
                    "track_name": record["track_name"],
                    "mp": record["start_mp"],
                    "lat": record["start_lat"],
                    "lon": record["start_lon"]
                }

                outfile.write(
                    json.dumps(location_record) + "\n"
                )

        #
        # END LOCATION
        #
        if (
            record.get("end_location")
            and record.get("end_lat") is not None
            and record.get("end_lon") is not None
        ):

            key = (
                record["end_location"],
                record["scac"],
                record["subdivision_id"]
            )

            if key not in seen:

                seen.add(key)

                location_record = {
                    "location_name": record["end_location"],
                    "source": "end",
                    "scac": record["scac"],
                    "subdivision_id": record["subdivision_id"],
                    "track_name": record["track_name"],
                    "mp": record["end_mp"],
                    "lat": record["end_lat"],
                    "lon": record["end_lon"]
                }

                outfile.write(
                    json.dumps(location_record) + "\n"
                )

print("Done")