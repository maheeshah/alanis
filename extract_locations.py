import json
import re

INPUT_FILE = r"C:\Users\mahee.shah\Downloads\bnsf_parsed_messages-2\bnsf_parsed_messages2.jsonl"
OUTPUT_FILE = r"C:\Users\mahee.shah\Desktop\trackproject\subdivs\Bulletin Search Results - Actual\location_extraction_bnsf.jsonl"


def clean_location(text):

    if not text:
        return None

    text = re.sub(r"\s+", " ", text).strip()

    # Remove common railroad instruction text that sometimes gets captured
    text = re.sub(
        r"\b(DO NOT EXCEED|MAXIMUM SPEED|SPEED RESTRICTION|AT SPEED)\b.*$",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = text.strip(" ,.-")

    if not text:
        return None

    return text

results = []

def is_valid_location(text):

    if not text:
        return False

    text = text.strip()

    # Reject obvious instructions
    bad_patterns = [
        r"DO NOT EXCEED",
        r"MAXIMUM SPEED",
        r"SPEED RESTRICTION",
        r"BOX\(ES\)",
        r"MARKED",
        r"TRACK WARRANT",
        r"IS OK AT",
        r"VOID AUTHORITY",
    ]

    for pattern in bad_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    return True

with open(INPUT_FILE, "r", encoding="utf-8") as f:

    for line_num, line in enumerate(f, start=1):

        try:
            msg = json.loads(line)
        except Exception:
            continue

        header = msg.get("header", {})
        body = msg.get("body", {})

        # Only 1051 authority messages
        if header.get("message_id") != 1051:
            continue

        authority_type_code = body.get("authority_type_code")

        if authority_type_code not in [1, 3]:
            continue

        scac = body.get("scac", "").strip().upper()
        authority_type = body.get("authority_type", "")
        authority_reference_number = body.get("authority_reference_number")

        text_lines = body.get("text", [])
        full_text = "\n".join(text_lines)

        start_location = None
        end_location = None

        #
        # ENTER MAIN
        #
        if authority_type_code == 3:

            m = re.search(
                r"AT LOC\s+(.*?)\s+HAS AUTHORITY",
                full_text,
                re.IGNORECASE
            )

            if m:
                start_location = clean_location(m.group(1))

        #
        # TRACK WARRANT
        #
        elif authority_type_code == 1:

            #
            # UP / BNSF
            #
            if scac in ["UP"]:

                from_match = re.search(
                    r"FROM\s+(.*?)(?:\s+ON|\n|$)",
                    full_text,
                    re.IGNORECASE
                )

                to_match = re.search(
                    r"TO\s+(.*?)(?:\s+ON|\n|$)",
                    full_text,
                    re.IGNORECASE
                )

                if from_match:
                    candidate = clean_location(from_match.group(1))
                    if is_valid_location(candidate):
                        start_location = candidate

                if to_match:
                    candidate = clean_location(to_match.group(1))
                    if is_valid_location(candidate):
                        end_location = candidate

            #
            # CSX
            #
            elif scac in ["CSXT"]:

                btw_match = re.search(
                    r"BTW\s+(.*?)\s+MAIN\s+TRK",
                    full_text,
                    re.IGNORECASE
                )

                and_match = re.search(
                    r"AND\s+(.*?)\s+MAIN\s+TRK",
                    full_text,
                    re.IGNORECASE
                )

                if btw_match:
                    candidate = clean_location(btw_match.group(1))
                    if is_valid_location(candidate):
                        start_location = candidate

                if and_match:
                    candidate = clean_location(and_match.group(1))
                    if is_valid_location(candidate):
                        end_location = candidate

            #
            # NS
            #
            elif scac in ["NS"]:

                from_match = re.search(
                    r"\bfrom\s+(.*?)(?:\n|$)",
                    full_text,
                    re.IGNORECASE
                )

                to_match = re.search(
                    r"\bto\s+(.*?)(?:\n|$)",
                    full_text,
                    re.IGNORECASE
                )

                if from_match:
                    candidate = clean_location(from_match.group(1))
                    if is_valid_location(candidate):
                        start_location = candidate

                if to_match:
                    candidate = clean_location(to_match.group(1))
                    if is_valid_location(candidate):
                        end_location = candidate


           
            # BNSF
            #
            elif scac == "BNSF":

                proceed_match = re.search(
                    r"PROCEED\s+FROM\s+(.*?)\s+TO\s+(.*?)\s+(?:ON\b|\n|$)",
                    full_text,
                    re.IGNORECASE
                )

                if proceed_match:

                    candidate = clean_location(proceed_match.group(1))
                    if is_valid_location(candidate):
                        start_location = candidate

                    candidate = clean_location(proceed_match.group(2))
                    if is_valid_location(candidate):
                        end_location = candidate

                else:

                    between_match = re.search(
                        r"WORK\s+BETWEEN\s+(.*?)\s+AND\s+(.*?)\s+(?:ON\b|\n|$)",
                        full_text,
                        re.IGNORECASE
                    )

                    if between_match:

                        candidate = clean_location(between_match.group(1))
                        if is_valid_location(candidate):
                            start_location = candidate

                        candidate = clean_location(between_match.group(2))
                        if is_valid_location(candidate):
                            end_location = candidate

                    else:

                        from_to_match = re.search(
                            r"FROM\s+(.*?)\s+TO\s+(.*?)(?:\s+ON|\n|$)",
                            full_text,
                            re.IGNORECASE
                        )

                        if from_to_match:

                            candidate = clean_location(from_to_match.group(1))
                            if is_valid_location(candidate):
                                start_location = candidate

                            candidate = clean_location(from_to_match.group(2))
                            if is_valid_location(candidate):
                                end_location = candidate

                    #
                    # Extract MP range from auth_segments
                    #
        
     
        auth_segments = body.get("auth_segments")

        # Skip records with no segments
        if not auth_segments:
            continue

        # Skip multi-segment authorities
        if len(auth_segments) != 1:
            continue

        seg = auth_segments[0]

        # Skip bidirectional authorities
        if seg.get("direction_code") == 2:
            continue



        start_mp = None
        end_mp = None
        track_name = None
        subdivision_id = None

        if auth_segments:
            seg = auth_segments[0]

            start_mp = seg.get("start_mp")
            end_mp = seg.get("end_mp")
            track_name = seg.get("track_name")
            subdivision_id = seg.get("subdivision_id")

        record = {
            "authority_reference_number": authority_reference_number,
            "scac": scac,
            "authority_type": authority_type,
            "start_location": start_location,
            "end_location": end_location,
            "start_mp": start_mp,
            "end_mp": end_mp,
            "track_name": track_name,
            "subdivision_id": subdivision_id
        }

        # Only save messages where we found at least one location
        if start_location or end_location:
            results.append(record)

with open(OUTPUT_FILE, "w", encoding="utf-8") as out:

    for row in results:
        out.write(json.dumps(row) + "\n")

print(f"Extracted {len(results):,} location records")
print(f"Saved to {OUTPUT_FILE}")