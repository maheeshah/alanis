
#!/usr/bin/env python3
from __future__ import annotations

import gc
import gzip
import json
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
from byte_decode import PTCDecoder  # type: ignore

# =====================================================
# CONFIGURATION
# =====================================================

START_DATE = datetime(2026, 6, 25)
END_DATE = datetime(2026, 6, 25)
MAX_THREADS = 1
MAX_FILES_PER_TRAIN = 500 # set to None to remove limit
TRAINS_OVERRIDE = ["CSXT3391/", "UP1982/"]
# set to None to auto-discover trains
# example of filtering: ["CSXT3391/", "UP1982/"]

# source toggling set to true/false per source if you want to include/exclude it
ENABLE_CSX = True
ENABLE_UP = True
ENABLE_BNSF = False

# UP layout is bucket/UP/<train>/<date>/CPU-1/disk/var/log/
UP_ROOT_PREFIX = "UP/"

# BNSF local root from iterator script.
BNSF_BASE_PATH = Path(r"C:\Users\Administrator\Desktop\Support Desk\BNSF\PTC Support")
BNSF_FILE_PATTERN = "app*.log.gz"

DEVICE_LOG_PATHS = [
    "CPU-1/disk/var/log/",
    # "CDU-1/var/log/",
]

ALLOWED_FILE_PREFIXES = ("app.", "chr.")
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSONL = BASE_DIR / "parsed_messages.jsonl"
OUTPUT_TRACK_SEGMENTS_JSONL = BASE_DIR / "track_seg_output.jsonl"
DEBUG = True
MAX_FILES = 5
CHR_MARKER = "VETMS_CHM_RECORDER:"


@dataclass(frozen=True)
class AwsSource:
    # One logical source = one bucket/prefix + one credential pair.
    name: str
    bucket: str
    root_prefix: str
    aws_access_key_id: str
    aws_secret_access_key: str
    region_name: str = "us-east-1"


@dataclass(frozen=True)
class AwsTrainTarget:
    source: AwsSource
    train_prefix: str


@dataclass(frozen=True)
class LocalFileTarget:
    source_name: str
    path: Path


# =====================================================
# AWS CLIENT
# =====================================================

CSX_SOURCE = AwsSource(
    name="CSX",
    bucket="csx.mdm.uploadarchive.raw",
    root_prefix="",
    aws_access_key_id="YOUR_AWS_ACCESS_KEY_ID",      # do not commit real credentials
    aws_secret_access_key="YOUR_AWS_SECRET_ACCESS_KEY",
    region_name="us-east-1",
)


UP_SOURCE = AwsSource(
    name="UP",
    bucket="up-wabtec-bucket",
    root_prefix=UP_ROOT_PREFIX,
    aws_access_key_id="YOUR_UP_AWS_ACCESS_KEY_ID",        # do not commit real credentials
    aws_secret_access_key="YOUR_UP_AWS_SECRET_ACCESS_KEY",
    region_name="us-east-2",
)

AWS_SOURCES: List[AwsSource] = []
if ENABLE_CSX:
    AWS_SOURCES.append(CSX_SOURCE)
if ENABLE_UP:
    AWS_SOURCES.append(UP_SOURCE)

AWS_CLIENTS: Dict[str, Any] = {}

for src in AWS_SOURCES:
    if not src.aws_access_key_id or not src.aws_secret_access_key:
        print(f"⚠️ Skipping {src.name}: missing AWS credentials")
        continue

    AWS_CLIENTS[src.name] = boto3.client(
        "s3",
        aws_access_key_id=src.aws_access_key_id,
        aws_secret_access_key=src.aws_secret_access_key,
        region_name=src.region_name,
    )

# Only fail if AWS is required but unavailable, or if both AWS and BNSF are disabled.
if not AWS_CLIENTS and AWS_SOURCES:
    if not ENABLE_BNSF:
        raise RuntimeError("No AWS clients available and BNSF is disabled")


# =====================================================
# DEBUG HELPER
# =====================================================

def dbg(msg: str) -> None:
    if DEBUG:
        print(msg)


# =====================================================
# DECODE HELPERS
# =====================================================

def looks_like_hex_blob(token: str, min_bytes: int = 1) -> bool:
    if not token:
        return False
    if len(token) < min_bytes * 2 or len(token) % 2 != 0:
        return False
    for ch in token:
        if ch not in "0123456789abcdefABCDEF":
            return False
    return True


def decode_full_message(raw_hex: str) -> Optional[Dict[str, Any]]:
    raw = bytes.fromhex(raw_hex)
    
    if DEBUG:
        print("RAW HEX START:", raw_hex[:20])
        print("RAW HEX MSG BYTES:", raw_hex[2:6])
        print("RAW HEX:", raw_hex)

    decoded = PTCDecoder(raw).decode()

    header = decoded.get("header") or {}
    message_id = header.get("message_id")
    if DEBUG:
        print("Decoded header:", header)
    if message_id not in (1041, 1051):
        return None


    return decoded


# =====================================================
# PARSE / STREAMING get_fixed_message_id
# =====================================================

def extract_chr_payload(line: str) -> str:
    idx = line.find(CHR_MARKER)
    if idx == -1:
        return ""
    return line[idx + len(CHR_MARKER):]


def extract_start_hex(payload: str) -> str:
    last_pipe = payload.rfind("|")
    if last_pipe != -1:
        payload = payload[last_pipe + 1:]
    if " " in payload:
        payload = payload.replace(" ", "")
    return payload


def build_track_segment_rows(decoded_message: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    header = decoded_message.get("header") or {}
    body = decoded_message.get("body") or {}
    is_1051 = header.get("message_id") == 1051
    if is_1051:
        segments = body.get("auth_segments", [])
    else:
        segments = body.get("segments", [])
    for segment in segments:

        rows.append({
            "subdivision": segment.get("subdivision_id"),
            "scac": body.get("scac"),
            "track_name": segment.get("track_name"),
            "start_prefix": segment.get("start_prefix"),
            "start_suffix": segment.get("start_suffix"),
            "start_mp": segment.get("start_mp"),
            "end_prefix": segment.get("end_prefix"),
            "end_suffix": segment.get("end_suffix"),
            "end_mp": segment.get("end_mp"),
        })

    return rows


def parse_content_from_lines(lines_iter, source_file: str) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    parsed_messages: List[Dict[str, Any]] = []
    track_segments: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    pending_hex: Optional[str] = None
    pending_message_id: Optional[str] = None
    pending_line_number: int = 0
    pending_continued_chunks = 0

    def clear_pending() -> None:
        nonlocal pending_hex, pending_message_id, pending_line_number, pending_continued_chunks
        pending_hex = None
        pending_message_id = None
        pending_line_number = 0
        pending_continued_chunks = 0

    def finalize_pending() -> None:
        nonlocal pending_hex, pending_message_id, pending_line_number, pending_continued_chunks

        
        if pending_hex is None or pending_message_id is None:
                return
        
        if DEBUG:
            print("ABOUT TO DECODE")
            print("pending_message_id:", pending_message_id)
            print("hex_len:", len(pending_hex))
            print("hex_even:", len(pending_hex) % 2 == 0)
            print("hex_start:", pending_hex[:40])
            print("hex_end:", pending_hex[-40:])
            print("contains_pipe:", "|" in pending_hex)



        try:
            decoded = decode_full_message(pending_hex)
        except Exception as e:
            if DEBUG:
                print("DECODE EXCEPTION:", repr(e))
                print("pending_message_id:", pending_message_id)
                print("hex_len:", len(pending_hex))
                print("hex_start:", pending_hex[:60])
                print("hex_end:", pending_hex[-60:])

            errors.append({
                "file": source_file,
                "line": pending_line_number,
                "message_id": pending_message_id,
                "error": f"DECODE ERROR: {e}",
            })
            clear_pending()
            return

        if decoded is not None:
            decoded["source_file"] = source_file
            decoded["line_number"] = pending_line_number
            decoded["continued_chunks"] = pending_continued_chunks
            parsed_messages.append(decoded)
            track_segments.extend(build_track_segment_rows(decoded))

        clear_pending()

    _diag_chr_lines = 0
    _diag_has_1041_1051 = 0
    _diag_first_chr_line: Optional[str] = None
    _diag_first_match_line: Optional[str] = None

    for line_number, line in enumerate(lines_iter, 1):

        if not line.startswith("CHR"):
            # diagnostic: catch lines that contain 1041/1051 but don't start with CHR
            if ("|1041|" in line or "|1051|" in line) and _diag_first_match_line is None:
                _diag_first_match_line = f"NON-CHR match at line {line_number}: {line[:120]!r}"
            continue

        _diag_chr_lines += 1
        if _diag_first_chr_line is None:
            _diag_first_chr_line = f"Line {line_number}: {line[:120]!r}"
        if "|1041|" in line or "|1051|" in line:
            _diag_has_1041_1051 += 1

 
        if len(line) >= 86:
            token = line[80:86]

            if "|EMP|" in line and DEBUG:
                print(f"Line {line_number}: token={token}")

            if token == "|1041|" or token == "|1051|":
                if DEBUG:
                    print(f"Line {line_number}: FOUND={token}")
                msg_id = token[1:5]

                finalize_pending()



                payload = extract_chr_payload(line)
                raw_hex = extract_start_hex(payload)

                pending_hex = raw_hex
                pending_message_id = msg_id
                pending_line_number = line_number
                pending_continued_chunks = 0

                continue

        if pending_hex is None:
            continue


        HEX_ONLY_RE = re.compile(r"^[0-9A-Fa-f]+$")
        payload = extract_chr_payload(line)
        if not payload:
            finalize_pending()
            continue

        payload = payload.replace(" ", "")

        if HEX_ONLY_RE.fullmatch(payload):
            pending_hex += payload
            pending_continued_chunks += 1
            continue

        finalize_pending()


    # Finalize any remaining pending message at end of file
    finalize_pending()

    print(f"[DIAG] {source_file}: chr_lines={_diag_chr_lines}, lines_with_1041_1051={_diag_has_1041_1051}")
    if _diag_first_chr_line:
        print(f"[DIAG] first CHR line: {_diag_first_chr_line}")
    if _diag_first_match_line:
        print(f"[DIAG] 1041/1051 in non-CHR line: {_diag_first_match_line}")

    if DEBUG:
        dbg(f"🧠 Fully decoded 1041/1051 messages in {source_file}: {len(parsed_messages)}")
        dbg(f"🛤 Track segment rows in {source_file}: {len(track_segments)}")
        dbg(f"⚠ Parse errors in {source_file}: {len(errors)}")

    return parsed_messages, track_segments, errors


def parse_content(text: str, source_file: str) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    return parse_content_from_lines(text.splitlines(), source_file)


# =====================================================
# FILE DISCOVERY / PROCESSING
# =====================================================

def parse_bnsf_date_folder(folder_name: str) -> Optional[datetime]:
    # BNSF date folders are expected like: "6-9-2026 Enforcement & Failed".
    try:
        date_part = folder_name.split(" ")[0]
        return datetime.strptime(date_part, "%m-%d-%Y")
    except Exception:
        return None


def iter_bnsf_local_files():
    """Generator that yields LocalFileTarget objects for BNSF local files."""
    if not ENABLE_BNSF:
        return

    file_count = 0
    for date_folder in BNSF_BASE_PATH.glob("*"):
        if not date_folder.is_dir():
            continue

        folder_date = parse_bnsf_date_folder(date_folder.name)
        if folder_date is None:
            continue

        if not (START_DATE <= folder_date <= END_DATE):
            continue

        for customer_folder in date_folder.glob("*"):
            if not customer_folder.is_dir():
                continue

            for year_folder in customer_folder.glob("*"):
                if not year_folder.name.isdigit():
                    continue

                for month_folder in year_folder.glob("*"):
                    if not month_folder.name.isdigit():
                        continue

                    cpu_path = month_folder / "CPU-1"
                    if not cpu_path.exists():
                        continue

                    for file_path in cpu_path.rglob(BNSF_FILE_PATTERN):
                        file_count += 1
                        if MAX_FILES_PER_TRAIN is not None and file_count > MAX_FILES_PER_TRAIN:
                            return
                        yield LocalFileTarget(source_name="BNSF", path=file_path)


def list_aws_trains() -> List[AwsTrainTarget]:
    trains: List[AwsTrainTarget] = []

    for source in AWS_SOURCES:
        client = AWS_CLIENTS.get(source.name)
        if client is None:
            continue

        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=source.bucket, Prefix=source.root_prefix, Delimiter="/"):
            for prefix_obj in page.get("CommonPrefixes", []):
                prefix = prefix_obj.get("Prefix")
                if isinstance(prefix, str):
                    trains.append(AwsTrainTarget(source=source, train_prefix=prefix))

    trains.sort(key=lambda t: (t.source.name, t.train_prefix))
    return trains


def process_single_aws_file(source: AwsSource, key: str):
    try:
        s3_client = AWS_CLIENTS[source.name]
        response = s3_client.get_object(Bucket=source.bucket, Key=key)
        body = response["Body"]
 
        with gzip.GzipFile(fileobj=body) as gz:
            line_iter = (line.decode("utf-8", errors="ignore").rstrip() for line in gz)
            parsed_messages, track_segments, errors = parse_content_from_lines(line_iter, key)

        location = f"{source.bucket}/{key}"
        if len(parsed_messages) > 0:
            print(f"🧠 Decoded {len(parsed_messages)} messages from {location}")
        for rec in parsed_messages:
            rec["location"] = location
        for rec in track_segments:
            rec["location"] = location

        return parsed_messages, track_segments, errors

    except Exception as e:
        return [], [], [{
            "file": key,
            "source": source.name,
            "storage": "s3",
            "location": f"{source.bucket}/{key}",
            "error": f"FILE ERROR: {e}",
        }]


def process_single_local_file(target: LocalFileTarget):
    try:
        source_file = str(target.path)
        with gzip.open(target.path, "rt", encoding="utf-8", errors="ignore") as f:
            parsed_messages, track_segments, errors = parse_content_from_lines(f, source_file)

        for rec in parsed_messages:
            rec["location"] = source_file
        for rec in track_segments:
            rec["location"] = source_file

        return parsed_messages, track_segments, errors

    except Exception as e:
        return [], [], [{
            "file": str(target.path),
            "error": f"FILE ERROR: {e}",
        }]


def process_aws_train(
    target: AwsTrainTarget,
    on_file_result: Optional[
        Callable[[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]], None]
    ] = None,
) -> Tuple[int, int, int, int]:
    total_parsed = 0
    total_track = 0
    total_errors = 0

    source = target.source
    train_prefix = target.train_prefix
    client = AWS_CLIENTS.get(source.name)
    if client is None:
        if on_file_result is not None:
            on_file_result([], [], [{"train": train_prefix, "source": source.name, "error": "Missing AWS client"}])
        return 0, 0, 0, 1

    print(f"▶ [{source.name}] Entering {train_prefix}")

    def iter_train_file_keys():
        paginator = client.get_paginator("list_objects_v2")
        file_count = 0

        for page in paginator.paginate(Bucket=source.bucket, Prefix=train_prefix, Delimiter="/"):
            for prefix_obj in page.get("CommonPrefixes", []):
                folder = prefix_obj["Prefix"]
                date_str = folder.rstrip("/").split("/")[-1]
                try:
                    folder_date = datetime.strptime(date_str, "%Y-%m-%d")
                except Exception:
                    continue

                if not (START_DATE <= folder_date <= END_DATE):
                    continue

                for device_path in DEVICE_LOG_PATHS:
                    log_prefix = f"{folder}{device_path}"
                    for log_page in paginator.paginate(Bucket=source.bucket, Prefix=log_prefix):
                        for obj in log_page.get("Contents", []):
                            key = obj["Key"]
                            if key.endswith("/") or not key.endswith(".gz"):
                                continue

                            filename = key.split("/")[-1].lower()
                            if not filename.startswith(ALLOWED_FILE_PREFIXES):
                                continue

                            file_count += 1
                            if MAX_FILES_PER_TRAIN is not None and file_count > MAX_FILES_PER_TRAIN:
                                return
                            yield key

    file_key_iter = iter_train_file_keys()
    processed_files = 0

    if MAX_THREADS > 1:
        max_in_flight = MAX_THREADS * 4
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as pool:
            futures: Dict[Any, str] = {}

            for key in file_key_iter:
                if len(futures) >= max_in_flight:
                    done, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                    for future in done:
                        finished_key = futures.pop(future)
                        try:
                            file_parsed, file_track, file_errors = future.result()
                            total_parsed += len(file_parsed)
                            total_track += len(file_track)
                            total_errors += len(file_errors)
                            processed_files += 1

                            if on_file_result is not None:
                                on_file_result(file_parsed, file_track, file_errors)

                            file_parsed.clear()
                            file_track.clear()
                            file_errors.clear()
                            gc.collect()

                            if processed_files % MAX_FILES == 0:
                                print(
                                    f"… [{source.name}] {train_prefix} processed {processed_files} files "
                                    f"(decoded {total_parsed}, track {total_track})"
                                )
                        except Exception as e:
                            total_errors += 1
                            if on_file_result is not None:
                                on_file_result(
                                    [],
                                    [],
                                    [{"file": finished_key, "source": source.name, "error": f"THREAD ERROR: {e}"}],
                                )

                futures[pool.submit(process_single_aws_file, source, key)] = key

            for future in as_completed(futures):
                finished_key = futures[future]
                try:
                    file_parsed, file_track, file_errors = future.result()
                    total_parsed += len(file_parsed)
                    total_track += len(file_track)
                    total_errors += len(file_errors)
                    processed_files += 1

                    if on_file_result is not None:
                        on_file_result(file_parsed, file_track, file_errors)

                    file_parsed.clear()
                    file_track.clear()
                    file_errors.clear()
                    gc.collect()

                    if processed_files % MAX_FILES == 0:
                        print(
                            f"… [{source.name}] {train_prefix} processed {processed_files} files "
                            f"(decoded {total_parsed}, track {total_track})"
                        )
                except Exception as e:
                    total_errors += 1
                    if on_file_result is not None:
                        on_file_result(
                            [],
                            [],
                            [{"file": finished_key, "source": source.name, "error": f"THREAD ERROR: {e}"}],
                        )
    else:
        for key in file_key_iter:
            file_parsed, file_track, file_errors = process_single_aws_file(source, key)
            total_parsed += len(file_parsed)
            total_track += len(file_track)
            total_errors += len(file_errors)
            processed_files += 1

            if on_file_result is not None:
                on_file_result(file_parsed, file_track, file_errors)

            file_parsed.clear()
            file_track.clear()
            file_errors.clear()
            gc.collect()

            if processed_files % MAX_FILES == 0:
                print(
                    f"… [{source.name}] {train_prefix} processed {processed_files} files "
                    f"(decoded {total_parsed}, track {total_track})"
                )

    print(f"✓ [{source.name}] {train_prefix} processed {processed_files} file(s), decoded {total_parsed}")
    return processed_files, total_parsed, total_track, total_errors


def process_bnsf_files(
    on_file_result: Optional[
        Callable[[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]], None]
    ] = None,
) -> Tuple[int, int, int, int]:
    total_parsed = 0
    total_track = 0
    total_errors = 0

    targets = list(iter_bnsf_local_files() or [])
    if not targets:
        return 0, 0, 0, 0

    print(f"▶ [BNSF] Entering local traversal ({len(targets)} file targets)")
    processed_files = 0

    if MAX_THREADS > 1:
        with ThreadPoolExecutor(max_workers=MAX_THREADS) as pool:
            future_map = {pool.submit(process_single_local_file, t): t for t in targets}
            for future in as_completed(future_map):
                target = future_map[future]
                try:
                    file_parsed, file_track, file_errors = future.result()
                    total_parsed += len(file_parsed)
                    total_track += len(file_track)
                    total_errors += len(file_errors)
                    processed_files += 1

                    if on_file_result is not None:
                        on_file_result(file_parsed, file_track, file_errors)

                    file_parsed.clear()
                    file_track.clear()
                    file_errors.clear()
                    gc.collect()

                    if processed_files % MAX_FILES == 0:
                        print(f"… [BNSF] processed {processed_files}/{len(targets)} files (decoded {total_parsed}, track {total_track})")
                except Exception as e:
                    total_errors += 1
                    if on_file_result is not None:
                        on_file_result(
                            [],
                            [],
                            [{"file": str(target.path), "source": "BNSF", "error": f"THREAD ERROR: {e}"}],
                        )
    else:
        for target in targets:
            file_parsed, file_track, file_errors = process_single_local_file(target)
            total_parsed += len(file_parsed)
            total_track += len(file_track)
            total_errors += len(file_errors)
            processed_files += 1

            if on_file_result is not None:
                on_file_result(file_parsed, file_track, file_errors)

            file_parsed.clear()
            file_track.clear()
            file_errors.clear()
            gc.collect()

            if processed_files % MAX_FILES == 0:
                print(f"… [BNSF] processed {processed_files}/{len(targets)} files (decoded {total_parsed}, track {total_track})")

    print(f"✓ [BNSF] processed {processed_files} file(s), decoded {total_parsed}")
    return processed_files, total_parsed, total_track, total_errors


# =====================================================
# EXPORTERS / MAIN
# =====================================================

class JsonlWriter:
    def __init__(self, filename: str | Path) -> None:
        self._fh = open(filename, "a", encoding="utf-8")

    def append(self, items: List[Dict[str, Any]]) -> None:
        for item in items:
            json.dump(item, self._fh, ensure_ascii=False)
            self._fh.write("\n")
            item.clear()
        self._fh.flush()
        items.clear()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()


def parse_aws_train_overrides(overrides: List[str]) -> List[AwsTrainTarget]:
    source_map = {s.name: s for s in AWS_SOURCES}
    targets: List[AwsTrainTarget] = []

    def normalize_prefix(source: AwsSource, raw_prefix: str) -> str:
        prefix = raw_prefix.strip()
        if not prefix.endswith("/"):
            prefix = f"{prefix}/"

        if source.name == "UP":
            root = source.root_prefix
            if root and not root.endswith("/"):
                root = f"{root}/"
            if root and not prefix.startswith(root):
                prefix = f"{root}{prefix}"

        return prefix

    for item in overrides:
        if ":" in item:
            src_name, prefix = item.split(":", 1)
            source = source_map.get(src_name.strip().upper())
            if source is None:
                raise ValueError(f"Unknown source in TRAINS_OVERRIDE: {src_name}")
            targets.append(AwsTrainTarget(source=source, train_prefix=normalize_prefix(source, prefix)))
            continue

        normalized_item = item.strip()

        up_source = source_map.get("UP")
        if up_source is not None and normalized_item.upper().startswith("UP"):
            targets.append(AwsTrainTarget(source=up_source, train_prefix=normalize_prefix(up_source, normalized_item)))
            continue

        csx = source_map.get("CSX")
        if csx is None:
            continue
        targets.append(AwsTrainTarget(source=csx, train_prefix=normalize_prefix(csx, normalized_item)))

    return targets


def main() -> None:
    aws_trains = parse_aws_train_overrides(TRAINS_OVERRIDE) if TRAINS_OVERRIDE else list_aws_trains()

    output_json = OUTPUT_JSONL
    output_track_segments_json = OUTPUT_TRACK_SEGMENTS_JSONL

    print("Using output files:")
    print(f"  JSONL: {output_json}")
    print(f"  Track JSONL: {output_track_segments_json}")

    total_decoded = 0
    total_track_segments = 0
    total_errors = 0
    batch_index = 0

    parsed_writer = JsonlWriter(output_json)
    track_writer = JsonlWriter(output_track_segments_json)

    def consume_batch(parsed_messages, track_segments, errors):
        nonlocal total_decoded, total_track_segments, total_errors, batch_index

        decoded_count = len(parsed_messages)
        track_count = len(track_segments)
        error_count = len(errors)

        if parsed_messages:
            parsed_writer.append(parsed_messages)
        if track_segments:
            track_writer.append(track_segments)

        batch_index += 1
        total_decoded += decoded_count
        total_track_segments += track_count
        total_errors += error_count

        print(
            f"batch {batch_index}: decoded={decoded_count} track={track_count} errors={error_count} | "
            f"totals decoded={total_decoded} track={total_track_segments} errors={total_errors}"
        )

        errors.clear()
        gc.collect()

    try:
        print("Running AWS train traversal")

        for target in aws_trains:
            label = f"[{target.source.name}] {target.train_prefix}"
            print(f"▶ Processing {label}")

            try:
                process_aws_train(target, on_file_result=consume_batch)
                gc.collect()
            except Exception as e:
                print(f"❌ Error in {label}: {e}")
                total_errors += 1

        if ENABLE_BNSF:
            print("▶ Processing BNSF local files")
            try:
                process_bnsf_files(on_file_result=consume_batch)
                gc.collect()
            except Exception as e:
                print(f"❌ Error in BNSF processing: {e}")
                total_errors += 1

    finally:
        parsed_writer.close()
        track_writer.close()

    print("Done")
    print(f"JSONL: {output_json}")
    print(f"Track JSONL: {output_track_segments_json}")
    print(f"Decoded: {total_decoded}")
    print(f"Track rows: {total_track_segments}")
    print(f"Errors: {total_errors}")


if __name__ == "__main__":
    main()
