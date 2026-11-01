import ipaddress
import json
import socket
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.parse import urlencode

import requests

try:
    from Crypto.Hash import keccak as crypto_keccak
except ImportError:
    crypto_keccak = None


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "sentro_clone"
# Vercel instances have an ephemeral filesystem. The local SQLite file is
# retained for development, while serverless invocations use /tmp.
DATABASE = Path(os.getenv("NORYX_DATABASE", "/tmp/noryx.sqlite3" if os.getenv("VERCEL") else str(ROOT / "noryx.sqlite3")))

def db_connect():
    return sqlite3.connect(DATABASE)
RPC_URLS = tuple(
    url
    for url in (
        os.getenv("NORYX_RPC_URL", "https://robinhood-rpc.publicnode.com"),
        os.getenv("NORYX_RPC_FALLBACK", "https://rpc.mainnet.chain.robinhood.com"),
    )
    if url
)
if not RPC_URLS:
    raise RuntimeError("At least one RPC URL must be configured")
CHAIN_ID = 4663
TRUST_PINNED_AT = "2026-10-25T12:01:50Z"
TRUST_CONTRACTS = (
    # Pinned values published by Sentro's custody endpoint on 2026-10-25.
    ("ur", 4663, "0x8876789976decbfcbbbe364623c63652db8c0904", "0x2ce6aaaf9f4151f5e1cbf774668772f17f532ae11b15e9284fd0a072a8b0fbde"),
    ("v3r", 4663, "0xcaf681a66d020601342297493863e78c959e5cb2", "0x6f36c378e272c6324c48f045182bcb54bd8ad654cf9ebd42e8893d52c4cb25dc"),
    ("weth", 4663, "0x0bd7d308f8e1639fab988df18a8011f41eacad73", "0x5706be52f64875fee65a2cec0d80e47a23d8793cbe85d214b48445e2d05f5353"),
    ("permit2", 4663, "0x000000000022d473030f116ddee9f6b43ac78ba3", "0x5208783f52488f7d3493e5e38311ab707c1d75457fe472a19b0b4d57d66a7fca"),
    ("delegate", 4663, "0xe6cae83bde06e4c305530e199d7217f42808555b", "0xcc7b633aef4b2543cb8f37522adf1a401f910f0f6b2430c1eecc11f401ccfcf3"),
    ("lighter", 4663, "0x94bab9693ba2f6358507effcbd372b0660afff9d", "0x19dbf90d4b88806f0ae0be5977d55062fcdf65210889d88ccd80ed25aae5aa5e"),
    ("usdg", 4663, "0x5fc5360d0400a0fd4f2af552add042d716f1d168", "0x864cc9ad53b338b82da1f7cab85ab0b3d5c8861acb422b6fec63cf36234f36a6"),
    ("launchpad", 4663, "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e", "0x89a27da6f703e0a7cdd4f233e7cb57604ff75b164530962d3ff7cf8483a67d84"),
    ("poolmanager", 4663, "0x8366a39cc670b4001a1121b8f6a443a643e40951", "0xbd3881180b547f5fe817545743cfb4343e96b1bc6640dcd70c106b0066e95626"),
    ("hook", 4663, "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044", "0xc21b1e6c1b45403e81a581f22ed6d9c747997af1cfdac1b1dc9f4b1d346a10db"),
    ("v3factory", 4663, "0x1f7d7550b1b028f7571e69a784071f0205fd2efa", "0xec72b1abd1f2faee020cfea9c646bd8994f9fb389054f6e574f103a895091739"),
    ("v3quoter", 4663, "0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7", "0x3db0868d945e9304c9bc6a8b2181948109ea617647142f3c4083e14393496a28"),
    ("relay_depository", 4663, "0x4cd00e387622c35bddb9b4c962c136462338bc31", "0xc8b9128d5bc2534ff2b2d7a45fd35a657ec345f5b9ad1d7a05b47b73d1ef4b07"),
    ("relay_depository", 8453, "0x4cd00e387622c35bddb9b4c962c136462338bc31", "0x77df38a47ee0c4453bc1bdc5f322712f0104ba1d97c4798dd49f16d4ed2e6256"),
    ("relay_receiver", 8453, "0xa5f565650890fba1824ee0f21ebbbf660a179934", "0x63c8abc3d5aa196fef7b9f43f9a2aeb1217361ccb131bf35f5588d32753a6c17"),
    ("relay_depository", 42161, "0x4cd00e387622c35bddb9b4c962c136462338bc31", "0x849d623d81c9334b401ae365455e32b0e248dc6af4e3a75b081b3d22114c24af"),
    ("relay_receiver", 42161, "0xa5f565650890fba1824ee0f21ebbbf660a179934", "0x63c8abc3d5aa196fef7b9f43f9a2aeb1217361ccb131bf35f5588d32753a6c17"),
    ("relay_depository", 1, "0x4cd00e387622c35bddb9b4c962c136462338bc31", "0x27fed69438cf2a1e69f053e52d5ee6f9637963c44da6035fb9241063240c799e"),
    ("relay_receiver", 1, "0xa5f565650890fba1824ee0f21ebbbf660a179934", "0x63c8abc3d5aa196fef7b9f43f9a2aeb1217361ccb131bf35f5588d32753a6c17"),
    ("relay_depository", 10, "0x4cd00e387622c35bddb9b4c962c136462338bc31", "0x766432ce88e81003090373438b2f1ada2ee87cc6f4fb91579e0e0878c726bdca"),
    ("relay_receiver", 10, "0xa5f565650890fba1824ee0f21ebbbf660a179934", "0x63c8abc3d5aa196fef7b9f43f9a2aeb1217361ccb131bf35f5588d32753a6c17"),
    ("pons_router", 4663, "0xe33e9e479df8802cb0866d5d05258bec4cf62948", "0xed9065184519eaa24a22c2556403d5d8bbb230ff94dbc5c414cf5028e20e52e7"),
    ("pons_escrow", 4663, "0xd3afeb2a57f70ef218aa82451c51b2fb0416ac9e", "0xf25f75cfbc1637ba068dc34f69098fa4e8a80f8ee8fe7bf7820594e0b3fed2f1"),
)
PRIVY_APP_ID = os.getenv("NORYX_PRIVY_APP_ID", "cmvxe2afu00660hl0olfwi7dl").strip()
INDEXER_URL = os.getenv("NORYX_INDEXER_URL", "").rstrip("/")
INDEXER_TIMEOUT = float(os.getenv("NORYX_INDEXER_TIMEOUT", "12"))
PONS_FACTORY = "0x7ed598bcef8bd9edd8c97a195c6d13f40801ec7e"
PONS_LAUNCH_TOPIC = "0x8d4aad4953d0ca700d468f3753aa14432d1b35b43ec6409f051fb6aa43a89607"
PONS_BUY_TOPIC = "0xec36bf571f136799e8dc0b0b8bea4b04d8bd3d43de838aab0d5fc21d4cbfc455"
PONS_SELL_TOPIC = "0x8113d738abdcb6b38357e9d53a54a7157861a09031b453651f0fe7fe151f59df"
PONS_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PONS_HOOK = "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"
PONS_POOL_MANAGER = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
PONS_UNIVERSAL_ROUTER = "0x8876789976decbfcbbbe364623c63652db8c0904"
PONS_PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3"
PONS_WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
PONS_V4_INITIALIZE_TOPIC = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
PONS_V4_SWAP_TOPIC = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"
PONS_V3_FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
PONS_WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
PONS_USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
PONS_V3_FEES = (100, 500, 3000, 10000)
PONS_FEED_WINDOW_BLOCKS = int(os.getenv("NORYX_PONS_FEED_WINDOW_BLOCKS", "100000"))
PONS_HISTORY_MAX_BLOCKS = int(os.getenv("NORYX_PONS_HISTORY_MAX_BLOCKS", "1500000"))
PONS_INDEXER_CHUNK_BLOCKS = int(os.getenv("NORYX_PONS_INDEXER_CHUNK_BLOCKS", "20000"))
PONS_INDEXER_POLL_SECONDS = float(os.getenv("NORYX_PONS_INDEXER_POLL_SECONDS", "2"))
PONS_INDEXER_OVERLAP_BLOCKS = max(1000, PONS_FEED_WINDOW_BLOCKS)
PONS_INDEXER_THREAD = None
PONS_INDEXER_LOCK = threading.Lock()
PONS_METADATA_CACHE = {}
PONS_BLOCK_TIME_CACHE = {}
PONS_TOKEN_RECORD_CACHE = {}
PONS_MARKET_CACHE = {}
PONS_LAUNCH_CACHE = {"updated_at": 0, "head": 0, "window_start": 0, "rows": [], "scan_truncated": False}
PONS_LAUNCH_CACHE_LOCK = threading.Lock()
PONS_BONDING_CACHE = {"updated_at": 0, "rows": []}
PONS_MIGRATED_CACHE = {"updated_at": 0, "rows": []}
PONS_LAUNCH_BLOCK_CACHE = {}
PONS_TRADE_LOG_CACHE = {}
PONS_TRADE_LOG_CACHE_LOCK = threading.Lock()
PONS_BLOCK_RATE_CACHE = {"updated_at": 0, "head": 0, "timestamp": 0, "rate": None}
PONS_TREND_CACHE = {}
PONS_TREND_LAUNCH_CACHE = {"updated_at": 0, "head": 0, "by_curve": {}}
PONS_TREND_LAUNCH_CACHE_LOCK = threading.Lock()
ETH_USD_CACHE = {"price": None, "updated_at": 0, "source": None}
ETH_USD_CACHE_LOCK = threading.Lock()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("NORYX_AI_API_KEY", "")).strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
IPFS_GATEWAYS = (
    "https://4everland.io/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://ipfs.io/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
)
IMAGE_HOSTS = {
    "m.rapidlaunch.io",
    "images.rapidlaunch.io",
    "images.pump.fun",
    "axiomtrading.sfo3.cdn.digitaloceanspaces.com",
    "axiom-rh-v2.axiom-cdn.io",
    "axiomtrading-v2.axiom-cdn.io",
    "fast-ipfs.com",
    "ipfs.launchblitz.ai",
    "pbs.twimg.com",
    "cdn.dexscreener.com",
    "raw.githubusercontent.com",
    "hexwarp.xyz",
    "gmgn.ai",
    "files.catbox.moe",
    "image.solanatracker.io",
    "j7m.io",
    "gateway.pinata.cloud",
    "4everland.io",
}


def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_error = None
    for rpc_url in RPC_URLS:
        for attempt in range(3):
            try:
                response = requests.post(
                    rpc_url,
                    json=payload,
                    headers={"user-agent": "Noryx/1.0", "accept": "application/json"},
                    timeout=15,
                )
                response.raise_for_status()
                body = response.json()
                if "error" in body:
                    raise RuntimeError(body["error"].get("message", "RPC request failed"))
                return body.get("result")
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                message = str(exc).lower()
                status = getattr(getattr(exc, "response", None), "status_code", None)
                rate_limited = status == 429 or "429" in message or "rate limit" in message
                if not rate_limited or attempt == 2:
                    break
                time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"All RPC endpoints failed: {last_error}")


def rpc_batch(calls):
    payload = [
        {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
        for index, (method, params) in enumerate(calls, start=1)
    ]
    last_error = None
    for rpc_url in RPC_URLS:
        for attempt in range(3):
            try:
                response = requests.post(
                    rpc_url,
                    json=payload,
                    headers={"user-agent": "Noryx/1.0", "accept": "application/json"},
                    timeout=20,
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, list):
                    raise ValueError("RPC batch response was not a list")
                responses = {item.get("id"): item for item in body if isinstance(item, dict)}
                results = []
                for index in range(1, len(payload) + 1):
                    item = responses.get(index)
                    if item is None:
                        raise ValueError(f"RPC batch response omitted request {index}")
                    if "error" in item:
                        raise RuntimeError(item["error"].get("message", "RPC batch request failed"))
                    results.append(item.get("result"))
                return results
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                last_error = exc
                message = str(exc).lower()
                status = getattr(getattr(exc, "response", None), "status_code", None)
                rate_limited = status == 429 or "429" in message or "rate limit" in message
                if not rate_limited or attempt == 2:
                    break
                time.sleep(0.25 * (attempt + 1))
    raise RuntimeError(f"All RPC endpoints failed for batch request: {last_error}")


def init_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS preferences (session_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tracked_wallets (session_id TEXT NOT NULL, address TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', PRIMARY KEY(session_id, address))"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pons_launches (
                token TEXT PRIMARY KEY,
                curve TEXT NOT NULL UNIQUE,
                pair_token TEXT NOT NULL,
                launch_block INTEGER NOT NULL,
                launch_tx TEXT,
                creator TEXT
            )"""
        )
        try:
            connection.execute("ALTER TABLE pons_launches ADD COLUMN creator TEXT")
        except sqlite3.OperationalError:
            pass
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pons_pools (
                pool_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                currency0 TEXT NOT NULL,
                currency1 TEXT NOT NULL,
                token_is_currency0 INTEGER NOT NULL,
                initialized_block INTEGER NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pons_market_trades (
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                token TEXT NOT NULL,
                venue TEXT NOT NULL,
                pool_id TEXT,
                side TEXT NOT NULL,
                quote_raw TEXT NOT NULL,
                token_raw TEXT NOT NULL,
                actor TEXT,
                recipient TEXT,
                block_number INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (tx_hash, log_index)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS pons_market_trades_token_time ON pons_market_trades(token, timestamp DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS pons_market_trades_time ON pons_market_trades(timestamp DESC)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS pons_market_index_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS token_meta (
                address TEXT PRIMARY KEY,
                image TEXT,
                description TEXT,
                x_url TEXT,
                x_handle TEXT,
                tg_url TEXT,
                site TEXT,
                updated_at INTEGER NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS token_transfers (
                tx_hash TEXT NOT NULL,
                log_index INTEGER NOT NULL,
                token TEXT NOT NULL,
                from_addr TEXT NOT NULL,
                to_addr TEXT NOT NULL,
                amount_raw TEXT NOT NULL,
                block_number INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (tx_hash, log_index)
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS token_transfers_token ON token_transfers(token, block_number)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS token_metrics (
                token TEXT PRIMARY KEY,
                holders INTEGER,
                top10_pct REAL,
                creator_pct REAL,
                dev_holds_pct REAL,
                buyers INTEGER,
                snipe_pct REAL,
                bundle_pct REAL,
                smart INTEGER,
                tax_bps INTEGER,
                score INTEGER,
                score_band TEXT,
                score_confidence TEXT,
                score_factors TEXT,
                score_unmeasured TEXT,
                updated_at INTEGER NOT NULL
            )"""
        )


def json_bytes(payload):
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def indexer_json(path, query):
    """Read live indexed market data from the configured compatible API."""
    if not INDEXER_URL:
        raise RuntimeError("No compatible indexer is configured; this endpoint is not served from Pons RPC yet.")
    url = f"{INDEXER_URL}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    response = requests.get(
        url,
        headers={"user-agent": "Noryx/1.0", "accept": "application/json"},
        timeout=INDEXER_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError("Indexer returned an invalid JSON shape")
    return payload


def decode_abi_string(value):
    raw = bytes.fromhex(value.removeprefix("0x"))
    if len(raw) >= 64:
        offset = int.from_bytes(raw[:32], "big")
        if offset + 32 <= len(raw):
            length = int.from_bytes(raw[offset : offset + 32], "big")
            end = offset + 32 + length
            if end <= len(raw):
                return raw[offset + 32 : end].decode("utf-8", errors="replace").strip("\x00")
    return raw[:32].rstrip(b"\x00").decode("utf-8", errors="replace")


def pons_token_metadata(address):
    address = address.lower()
    cached = PONS_METADATA_CACHE.get(address)
    if cached is not None:
        return cached
    metadata = {}
    errors = []
    calls = [
        ("eth_call", [{"to": address, "data": selector}, "latest"])
        for selector in ("0x06fdde03", "0x95d89b41", "0x313ce567")
    ]
    try:
        results = rpc_batch(calls)
    except (RuntimeError, ValueError, TypeError):
        results = [None, None, None]
    for index, field in enumerate(("name", "symbol")):
        try:
            result = results[index]
            if not isinstance(result, str):
                result = rpc_call("eth_call", calls[index][1])
            metadata[field] = decode_abi_string(result)
        except (RuntimeError, ValueError, TypeError) as exc:
            errors.append(f"{field}: {exc}")
    try:
        result = results[2]
        if not isinstance(result, str):
            result = rpc_call("eth_call", calls[2][1])
        metadata["decimals"] = int(result, 16)
    except (RuntimeError, ValueError, TypeError) as exc:
        errors.append(f"decimals: {exc}")
    metadata["metadata_available"] = not errors
    if errors:
        metadata["metadata_error"] = "; ".join(errors)
    PONS_METADATA_CACHE[address] = metadata
    return metadata


TOKEN_META_CACHE = {}
TOKEN_META_LOCK = threading.Lock()
TOKEN_META_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="noryx-meta")
TOKEN_META_FETCHING = set()


def decode_socials_tuple(raw_hex):
    if not raw_hex or len(raw_hex) < 66:
        return []
    try:
        raw = bytes.fromhex(raw_hex.removeprefix("0x"))
        if len(raw) < 32:
            return []
        num_heads = int.from_bytes(raw[:32], "big") // 32
        if num_heads <= 0 or num_heads > 10:
            return []
        strings = []
        for i in range(num_heads):
            offset = int.from_bytes(raw[i * 32 : (i + 1) * 32], "big")
            if offset + 32 <= len(raw):
                length = int.from_bytes(raw[offset : offset + 32], "big")
                end = offset + 32 + length
                if end <= len(raw):
                    val = raw[offset + 32 : end].decode("utf-8", errors="replace").strip("\x00")
                    strings.append(val)
        return strings
    except Exception:
        return []


def _fetch_token_metadata_extra_sync(address):
    address = address.lower()
    calls = [
        ("eth_call", [{"to": address, "data": "0xfb7f21eb"}, "latest"]),
        ("eth_call", [{"to": address, "data": "0x7284e416"}, "latest"]),
        ("eth_call", [{"to": address, "data": "0x53cd512a"}, "latest"]),
    ]
    try:
        results = rpc_batch(calls)
    except Exception:
        results = [None, None, None]

    img_raw = decode_abi_string(results[0]) if results[0] else None
    desc_raw = decode_abi_string(results[1]) if results[1] else None
    socs = decode_socials_tuple(results[2]) if results[2] else []

    image = img_raw
    description = desc_raw
    x_url = None
    x_handle = None
    tg_url = None
    site = None

    for s in socs:
        s = s.strip()
        if not s:
            continue
        low = s.lower()
        if "twitter.com" in low or "x.com" in low:
            if not x_url:
                x_url = s
                parsed_path = urlparse(s).path.strip("/").split("/")
                if parsed_path and parsed_path[0] and parsed_path[0] not in ("i", "intent"):
                    x_handle = parsed_path[0].lstrip("@").split("?")[0]
        elif "t.me" in low or "telegram.me" in low:
            if not tg_url:
                tg_url = s
        elif low.startswith(("http://", "https://")):
            if not site:
                site = s

    if image and (image.endswith(".json") or "/metadata" in image):
        try:
            fetch_url = image
            if image.startswith("ipfs://"):
                fetch_url = IPFS_GATEWAYS[0] + image[7:].removeprefix("ipfs/")
            r = requests.get(fetch_url, headers={"user-agent": "Noryx/1.0"}, timeout=3)
            if r.status_code == 200 and "application/json" in r.headers.get("content-type", ""):
                meta_json = r.json()
                if isinstance(meta_json, dict):
                    image = meta_json.get("image") or meta_json.get("image_url") or meta_json.get("imageUrl") or image
                    if not description:
                        description = meta_json.get("description") or meta_json.get("desc")
                    if not x_url:
                        x_url = meta_json.get("twitter") or meta_json.get("x")
                    if not tg_url:
                        tg_url = meta_json.get("telegram") or meta_json.get("tg")
                    if not site:
                        site = meta_json.get("website") or meta_json.get("site")
        except Exception:
            pass

    if image:
        image = image.strip()
        if not (image.startswith("ipfs://") or image.startswith("https://") or re.fullmatch(r"[A-Za-z0-9_-]{20,100}", image)):
            if image.startswith("http://"):
                image = "https://" + image[7:]
            else:
                image = None

    record = {
        "address": address,
        "image": image,
        "description": description or "",
        "x_url": x_url,
        "x_handle": x_handle,
        "tg_url": tg_url,
        "site": site,
        "updated_at": int(time.time()),
    }

    try:
        with sqlite3.connect(DATABASE) as conn:
            conn.execute(
                """INSERT INTO token_meta(address, image, description, x_url, x_handle, tg_url, site, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(address) DO UPDATE SET
                       image = excluded.image,
                       description = excluded.description,
                       x_url = excluded.x_url,
                       x_handle = excluded.x_handle,
                       tg_url = excluded.tg_url,
                       site = excluded.site,
                       updated_at = excluded.updated_at""",
                (
                    address,
                    record["image"],
                    record["description"],
                    record["x_url"],
                    record["x_handle"],
                    record["tg_url"],
                    record["site"],
                    record["updated_at"],
                ),
            )
    except sqlite3.Error:
        pass

    with TOKEN_META_LOCK:
        TOKEN_META_CACHE[address] = record
    return record


def pons_token_metadata_extra(address, sync_fallback=False):
    address = address.lower()
    with TOKEN_META_LOCK:
        cached = TOKEN_META_CACHE.get(address)
        if cached is not None:
            return cached

    try:
        with sqlite3.connect(DATABASE) as conn:
            row = conn.execute(
                "SELECT image, description, x_url, x_handle, tg_url, site, updated_at FROM token_meta WHERE address = ?",
                (address,),
            ).fetchone()
            if row is not None:
                record = {
                    "address": address,
                    "image": row[0],
                    "description": row[1],
                    "x_url": row[2],
                    "x_handle": row[3],
                    "tg_url": row[4],
                    "site": row[5],
                    "updated_at": row[6],
                }
                with TOKEN_META_LOCK:
                    TOKEN_META_CACHE[address] = record
                return record
    except sqlite3.Error:
        pass

    if sync_fallback:
        return _fetch_token_metadata_extra_sync(address)

    with TOKEN_META_LOCK:
        if address not in TOKEN_META_FETCHING:
            TOKEN_META_FETCHING.add(address)
            def bg_task():
                try:
                    _fetch_token_metadata_extra_sync(address)
                finally:
                    with TOKEN_META_LOCK:
                        TOKEN_META_FETCHING.discard(address)
            TOKEN_META_EXECUTOR.submit(bg_task)

    return {}


TOKEN_METRICS_CACHE = {}
TOKEN_METRICS_LOCK = threading.Lock()
TOKEN_METRICS_FETCHING = set()
TOKEN_METRICS_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="noryx-metrics")


def pons_token_holders_and_metrics(address, creator=None, sync_fallback=True):
    address = address.lower()
    now_ts = int(time.time())

    with sqlite3.connect(DATABASE) as connection:
        launch = connection.execute(
            "SELECT curve, pair_token, launch_block, launch_tx, creator FROM pons_launches WHERE token = ?",
            (address,),
        ).fetchone()

    if not launch:
        return None, {
            "count": 0,
            "total_holders": 0,
            "top10_pct": None,
            "holders": [],
            "partial": False,
        }

    curve, pair_token, launch_block, launch_tx, db_creator = launch
    if not creator:
        creator = db_creator

    with sqlite3.connect(DATABASE) as connection:
        tf_count = connection.execute(
            "SELECT COUNT(*) FROM token_transfers WHERE token = ?",
            (address,),
        ).fetchone()[0]

    if tf_count == 0 and sync_fallback:
        try:
            cur_blk = int(rpc_call("eth_blockNumber", []), 16)
            logs = pons_index_get_logs(
                {"address": address, "topics": [PONS_TRANSFER_TOPIC]},
                launch_block,
                cur_blk,
            )
            if logs:
                tf_blocks = {int(log["blockNumber"], 16) for log in logs}
                tf_timestamps = pons_block_timestamps(tf_blocks)
                new_rows = []
                for log in logs:
                    topics = log.get("topics", [])
                    data = log.get("data", "0x")
                    if len(topics) < 3:
                        continue
                    src = "0x" + topics[1][-40:].lower()
                    dst = "0x" + topics[2][-40:].lower()
                    val_raw = str(int(data, 16)) if data != "0x" else "0"
                    blk = int(log["blockNumber"], 16)
                    ts = tf_timestamps.get(blk, 0)
                    tx_h = log.get("transactionHash", "").lower()
                    log_idx = int(log.get("logIndex", "0x0"), 16)
                    new_rows.append((tx_h, log_idx, address, src, dst, val_raw, blk, ts))
                with sqlite3.connect(DATABASE) as connection:
                    connection.executemany(
                        """INSERT OR IGNORE INTO token_transfers(
                            tx_hash, log_index, token, from_addr, to_addr, amount_raw, block_number, timestamp
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                        new_rows,
                    )
        except Exception:
            pass

    with sqlite3.connect(DATABASE) as connection:
        rows = connection.execute(
            "SELECT from_addr, to_addr, amount_raw, block_number FROM token_transfers WHERE token = ?",
            (address,),
        ).fetchall()
        pools = connection.execute(
            "SELECT pool_id FROM pons_pools WHERE token = ?",
            (address,),
        ).fetchall()
        trade_rows = connection.execute(
            "SELECT actor, side, token_raw, block_number FROM pons_market_trades WHERE token = ?",
            (address,),
        ).fetchall()

    balances = defaultdict(int)
    for from_addr, to_addr, amount_raw, blk in rows:
        val = int(amount_raw)
        balances[to_addr] += val
        balances[from_addr] -= val

    total_supply = sum(v for k, v in balances.items() if v > 0)
    if total_supply <= 0:
        total_supply = 10**9 * 10**18

    system_addrs = {
        curve.lower(): "curve",
        PONS_POOL_MANAGER.lower(): "pool manager",
        PONS_HOOK.lower(): "pool hook",
        PONS_UNIVERSAL_ROUTER.lower(): "router",
        "0x" + "0" * 40: "burned",
        "0x" + "0" * 38 + "dead": "burned",
    }
    for p in pools:
        system_addrs[p[0].lower()] = "pool"

    buyers_set = set()
    snipe_tokens = 0
    snipe_actors = set()
    for actor, side, tok_raw, blk in trade_rows:
        if side == "buy" and actor:
            actor_l = actor.lower()
            buyers_set.add(actor_l)
            if blk <= launch_block + 2:
                if not creator or actor_l != creator.lower():
                    snipe_tokens += int(tok_raw)
                    snipe_actors.add(actor_l)

    buyers = len(buyers_set)
    snipe_pct = round(snipe_tokens / total_supply * 100.0, 2) if total_supply > 0 else 0.0

    creator_lower = creator.lower() if creator else None
    creator_balance = balances.get(creator_lower, 0) if creator_lower else 0
    creator_pct = round(creator_balance / total_supply * 100.0, 2) if total_supply > 0 else 0.0

    real_holders = []
    all_holder_rows = []
    sorted_holders = sorted(balances.items(), key=lambda x: x[1], reverse=True)

    metadata = pons_token_metadata(address)
    decimals = metadata.get("decimals") if isinstance(metadata.get("decimals"), int) else 18

    rank = 1
    for addr, bal in sorted_holders:
        if bal <= 0:
            continue
        pct = round(bal / total_supply * 100.0, 2) if total_supply > 0 else 0.0
        addr_l = addr.lower()
        if addr_l in system_addrs:
            lbl = system_addrs[addr_l]
        elif creator_lower and addr_l == creator_lower:
            lbl = "creator"
        elif addr_l in snipe_actors:
            lbl = "sniper"
        else:
            lbl = "wallet"

        item = {
            "address": addr,
            "wallet": addr,
            "balance": str(bal),
            "amount": str(Decimal(bal) / Decimal(10**decimals)),
            "pct": pct,
            "label": lbl,
            "rank": rank,
        }
        all_holder_rows.append(item)
        if lbl in ("wallet", "creator", "sniper"):
            real_holders.append(item)
            rank += 1

    holders_count = len(real_holders)
    top10 = real_holders[:10]
    top10_pct = round(sum(h["pct"] for h in top10), 2) if top10 else 0.0

    progress = 0.0
    try:
        record = pons_factory_record(address)
        if record:
            if record["phase"] != 0:
                progress = 100.0
            else:
                curve_bal = pons_eth_balance(curve)
                threshold = pons_curve_threshold()
                if threshold > 0:
                    progress = min(100.0, curve_bal * 100.0 / threshold)
    except Exception:
        pass

    if top10_pct <= 20: top10_pts = 25
    elif top10_pct <= 35: top10_pts = 20
    elif top10_pct <= 50: top10_pts = 15
    elif top10_pct <= 70: top10_pts = 10
    else: top10_pts = 5

    if creator_pct <= 2: creator_pts = 20
    elif creator_pct <= 5: creator_pts = 15
    elif creator_pct <= 10: creator_pts = 10
    elif creator_pct <= 20: creator_pts = 5
    else: creator_pts = 0

    if snipe_pct == 0: snipers_pts = 15
    elif snipe_pct <= 5: snipers_pts = 12
    elif snipe_pct <= 15: snipers_pts = 8
    elif snipe_pct <= 30: snipers_pts = 4
    else: snipers_pts = 0

    if buyers >= 50: buyers_pts = 20
    elif buyers >= 20: buyers_pts = 15
    elif buyers >= 10: buyers_pts = 10
    elif buyers >= 3: buyers_pts = 5
    else: buyers_pts = 2

    if progress >= 80: curve_pts = 20
    elif progress >= 50: curve_pts = 15
    elif progress >= 20: curve_pts = 10
    else: curve_pts = 5

    raw_score = top10_pts + creator_pts + snipers_pts + buyers_pts + curve_pts
    score = max(0, min(100, raw_score))

    if score >= 70: score_band = "strong"
    elif score >= 50: score_band = "fair"
    elif score >= 35: score_band = "weak"
    else: score_band = "risky"

    score_factors = [
        {"id": "top10", "label": "Top 10 hold", "points": top10_pts, "max": 25, "value_text": f"{top10_pct}%", "measured": True},
        {"id": "creator", "label": "Creator holds", "points": creator_pts, "max": 20, "value_text": f"{creator_pct}%", "measured": True},
        {"id": "snipers", "label": "Snipers", "points": snipers_pts, "max": 15, "value_text": f"{snipe_pct}%", "measured": True},
        {"id": "buyers", "label": "Buyers", "points": buyers_pts, "max": 20, "value_text": str(buyers), "measured": True},
        {"id": "curve", "label": "Bonding curve", "points": curve_pts, "max": 20, "value_text": f"{round(progress)}%", "measured": True},
    ]
    score_unmeasured = ["bundle", "contract_audit"]

    metrics_dict = {
        "holders": holders_count,
        "buyers": buyers,
        "top10_pct": top10_pct,
        "creator_pct": creator_pct,
        "dev_holds_pct": creator_pct,
        "snipe_pct": snipe_pct,
        "bundle_pct": None,
        "smart": 0,
        "tax_bps": 0,
        "score": score,
        "score_band": score_band,
        "score_confidence": "partial",
        "score_factors": score_factors,
        "score_unmeasured": score_unmeasured,
        "updated_at": now_ts,
    }

    try:
        with sqlite3.connect(DATABASE) as connection:
            connection.execute(
                """INSERT INTO token_metrics(
                    token, holders, top10_pct, creator_pct, dev_holds_pct, buyers, snipe_pct,
                    bundle_pct, smart, tax_bps, score, score_band, score_confidence,
                    score_factors, score_unmeasured, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    holders = excluded.holders,
                    top10_pct = excluded.top10_pct,
                    creator_pct = excluded.creator_pct,
                    dev_holds_pct = excluded.dev_holds_pct,
                    buyers = excluded.buyers,
                    snipe_pct = excluded.snipe_pct,
                    bundle_pct = excluded.bundle_pct,
                    smart = excluded.smart,
                    tax_bps = excluded.tax_bps,
                    score = excluded.score,
                    score_band = excluded.score_band,
                    score_confidence = excluded.score_confidence,
                    score_factors = excluded.score_factors,
                    score_unmeasured = excluded.score_unmeasured,
                    updated_at = excluded.updated_at""",
                (
                    address,
                    holders_count,
                    top10_pct,
                    creator_pct,
                    creator_pct,
                    buyers,
                    snipe_pct,
                    None,
                    0,
                    0,
                    score,
                    score_band,
                    "partial",
                    json.dumps(score_factors),
                    json.dumps(score_unmeasured),
                    now_ts,
                ),
            )
    except sqlite3.Error:
        pass

    with TOKEN_METRICS_LOCK:
        TOKEN_METRICS_CACHE[address] = metrics_dict

    holders_response = {
        "count": holders_count,
        "total_holders": holders_count,
        "top10_pct": top10_pct,
        "holders": all_holder_rows,
        "partial": False,
    }
    return metrics_dict, holders_response


def pons_token_metrics(address, sync_fallback=False):
    address = address.lower()
    now_ts = int(time.time())

    with TOKEN_METRICS_LOCK:
        cached = TOKEN_METRICS_CACHE.get(address)
        if cached is not None and (now_ts - cached.get("updated_at", 0) < 60 or not sync_fallback):
            return cached

    try:
        with sqlite3.connect(DATABASE) as connection:
            row = connection.execute(
                """SELECT holders, top10_pct, creator_pct, dev_holds_pct, buyers, snipe_pct,
                          bundle_pct, smart, tax_bps, score, score_band, score_confidence,
                          score_factors, score_unmeasured, updated_at
                   FROM token_metrics WHERE token = ?""",
                (address,),
            ).fetchone()
            if row is not None:
                factors = json.loads(row[12]) if row[12] else []
                unmeasured = json.loads(row[13]) if row[13] else []
                metrics = {
                    "holders": row[0],
                    "top10_pct": row[1],
                    "creator_pct": row[2],
                    "dev_holds_pct": row[3],
                    "buyers": row[4],
                    "snipe_pct": row[5],
                    "bundle_pct": row[6],
                    "smart": row[7],
                    "tax_bps": row[8],
                    "score": row[9],
                    "score_band": row[10],
                    "score_confidence": row[11],
                    "score_factors": factors,
                    "score_unmeasured": unmeasured,
                    "updated_at": row[14],
                }
                with TOKEN_METRICS_LOCK:
                    TOKEN_METRICS_CACHE[address] = metrics
                if now_ts - row[14] < 120 or not sync_fallback:
                    return metrics
    except sqlite3.Error:
        pass

    if sync_fallback:
        metrics, _ = pons_token_holders_and_metrics(address, None, True)
        return metrics

    with TOKEN_METRICS_LOCK:
        if address not in TOKEN_METRICS_FETCHING:
            TOKEN_METRICS_FETCHING.add(address)
            def bg_task():
                try:
                    pons_token_holders_and_metrics(address, None, True)
                finally:
                    with TOKEN_METRICS_LOCK:
                        TOKEN_METRICS_FETCHING.discard(address)
            TOKEN_METRICS_EXECUTOR.submit(bg_task)

    return None


def pons_token_holders(address, creator=None):
    _, holders_resp = pons_token_holders_and_metrics(address, creator=creator, sync_fallback=True)
    return holders_resp



def pons_token_traders(address):
    """Top wallets for a token by buy/sell volume from the local index."""
    address = address.lower()
    db = db_connect()
    try:
        # Sum buys/sells per actor
        rows = db.execute(
            """
            SELECT
                actor,
                SUM(CASE WHEN side='buy'  THEN CAST(quote_raw AS REAL)/1e18 ELSE 0 END) AS bought_eth,
                SUM(CASE WHEN side='sell' THEN CAST(quote_raw AS REAL)/1e18 ELSE 0 END) AS sold_eth,
                COUNT(*) AS trades,
                SUM(CASE WHEN side='buy'  THEN 1 ELSE 0 END) AS buys,
                SUM(CASE WHEN side='sell' THEN 1 ELSE 0 END) AS sells
            FROM pons_market_trades
            WHERE token=? AND actor IS NOT NULL AND actor != ''
            GROUP BY actor
            ORDER BY bought_eth DESC
            LIMIT 50
            """,
            (address,),
        ).fetchall()
    finally:
        db.close()

    traders = []
    for rank, row in enumerate(rows, start=1):
        actor, bought_eth, sold_eth, trades, buys, sells = row
        pnl_eth = sold_eth - bought_eth
        traders.append({
            "address": actor,
            "rank": rank,
            "bought_eth": round(float(bought_eth), 6),
            "sold_eth": round(float(sold_eth), 6),
            "pnl_eth": round(float(pnl_eth), 6),
            "trades": trades,
            "buys": buys,
            "sells": sells,
        })
    partial = len(traders) == 0
    return {"traders": traders, "count": len(traders), "partial": partial, "source": "pons_index"}


def pons_trend_token_info(address):
    address = address.lower()
    metadata = PONS_METADATA_CACHE.get(address)
    supply_raw = None
    supply_error = None
    if metadata is None:
        calls = [
            ("eth_call", [{"to": address, "data": selector}, "latest"])
            for selector in ("0x06fdde03", "0x95d89b41", "0x313ce567", "0x18160ddd")
        ]
        try:
            results = rpc_batch(calls)
            if not all(isinstance(result, str) for result in results):
                raise ValueError("Pons returned incomplete token metadata or supply")
            metadata = {
                "name": decode_abi_string(results[0]),
                "symbol": decode_abi_string(results[1]),
                "decimals": int(results[2], 16),
                "metadata_available": True,
            }
            PONS_METADATA_CACHE[address] = metadata
            supply_raw = int(results[3], 16)
        except (RuntimeError, ValueError, TypeError, IndexError) as exc:
            metadata = pons_token_metadata(address)
            supply_error = str(exc)
    if supply_raw is None:
        try:
            result = rpc_call(
                "eth_call",
                [{"to": address, "data": "0x18160ddd"}, "latest"],
            )
            supply_raw = int(result, 16)
            supply_error = None
        except (RuntimeError, ValueError, TypeError) as exc:
            supply_error = str(exc)
    return metadata, supply_raw, supply_error


def pons_block_timestamp(block_number):
    cached = PONS_BLOCK_TIME_CACHE.get(block_number)
    if cached is not None:
        return cached
    block = rpc_call("eth_getBlockByNumber", [hex(block_number), False])
    if not isinstance(block, dict) or not block.get("timestamp"):
        raise ValueError(f"RPC did not return a timestamp for block {block_number}")
    timestamp = int(block["timestamp"], 16)
    PONS_BLOCK_TIME_CACHE[block_number] = timestamp
    return timestamp


def pons_block_timestamps(block_numbers):
    unique_blocks = sorted(set(block_numbers))
    timestamps = {
        block_number: PONS_BLOCK_TIME_CACHE[block_number]
        for block_number in unique_blocks
        if block_number in PONS_BLOCK_TIME_CACHE
    }
    missing = [block_number for block_number in unique_blocks if block_number not in timestamps]
    chunks = [missing[index : index + 200] for index in range(0, len(missing), 200)]

    def fetch_chunk(blocks):
        calls = [
            ("eth_getBlockByNumber", [hex(block_number), False])
            for block_number in blocks
        ]
        try:
            results = rpc_batch(calls)
            chunk_times = {}
            for block_number, block in zip(blocks, results):
                if not isinstance(block, dict) or not block.get("timestamp"):
                    raise ValueError(f"RPC did not return a timestamp for block {block_number}")
                timestamp = int(block["timestamp"], 16)
                PONS_BLOCK_TIME_CACHE[block_number] = timestamp
                chunk_times[block_number] = timestamp
            return chunk_times
        except (RuntimeError, ValueError):
            with ThreadPoolExecutor(max_workers=min(16, len(blocks))) as executor:
                values = list(executor.map(pons_block_timestamp, blocks))
            return dict(zip(blocks, values))

    if chunks:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as executor:
            for chunk_times in executor.map(fetch_chunk, chunks):
                timestamps.update(chunk_times)
    return timestamps


def pons_factory_record(address):
    address = address.lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", address):
        return None
    cached = PONS_TOKEN_RECORD_CACHE.get(address)
    if cached is not None and time.time() - cached[0] < 2:
        return cached[1]
    result = rpc_call(
        "eth_call",
        [
            {"to": PONS_FACTORY, "data": "0x3cf28b5a" + address[2:].rjust(64, "0")},
            "latest",
        ],
    )
    if not isinstance(result, str) or len(result) < 2 + 15 * 64:
        return None
    words = [result[2 + index * 64 : 2 + (index + 1) * 64] for index in range(15)]
    record = {
        "token": "0x" + words[0][-40:],
        "curve": "0x" + words[1][-40:],
        "pair_token": "0x" + words[4][-40:],
        "phase": int(words[10], 16),
        "tick_spacing": int(words[7], 16) if words[7] else 0,
        "exists": int(words[14], 16) == 1,
    }
    if not record["exists"] or record["token"].lower() != address:
        return None
    PONS_TOKEN_RECORD_CACHE[address] = (time.time(), record)
    return record


def pons_launch_logs(start_block, end_block):
    logs = []
    chunk_size = 20_000
    for chunk_start in range(start_block, end_block + 1, chunk_size):
        chunk_end = min(end_block, chunk_start + chunk_size - 1)
        chunk = rpc_call(
            "eth_getLogs",
            [
                {
                    "address": PONS_FACTORY,
                    "fromBlock": hex(chunk_start),
                    "toBlock": hex(chunk_end),
                    "topics": [PONS_LAUNCH_TOPIC],
                }
            ],
        )
        if not isinstance(chunk, list):
            raise ValueError("Pons RPC returned an invalid log list")
        logs.extend(chunk)
    return logs


def pons_launch_row(log):
    topics = log.get("topics", [])
    data = log.get("data", "0x")[2:]
    if len(topics) < 4 or len(data) < 192:
        raise ValueError("Pons factory returned a malformed TokenLaunched event")
    token = "0x" + topics[1][-40:]
    curve = "0x" + topics[2][-40:]
    deployer = "0x" + topics[3][-40:]
    record = pons_factory_record(token)
    if record is None:
        raise ValueError(f"Pons factory has no current launch record for {token}")
    words = [data[index : index + 64] for index in range(0, 192, 64)]
    pair_token = record["pair_token"]
    block_number = int(log["blockNumber"], 16)
    PONS_LAUNCH_BLOCK_CACHE[token.lower()] = (time.time(), block_number)
    timestamp = pons_block_timestamp(block_number)
    metadata = pons_token_metadata(token)
    meta_extra = pons_token_metadata_extra(token)
    row = {
        "token": token,
        "name": metadata.get("name", ""),
        "symbol": metadata.get("symbol", ""),
        "decimals": metadata.get("decimals"),
        "metadata_available": metadata["metadata_available"],
        "image": meta_extra.get("image"),
        "x_url": meta_extra.get("x_url"),
        "x_handle": meta_extra.get("x_handle"),
        "tg_url": meta_extra.get("tg_url"),
        "site": meta_extra.get("site"),
        "description": meta_extra.get("description"),
        "chain_id": CHAIN_ID,
        "curve": curve,
        "phase": record["phase"],
        "deployer": deployer,
        "pair_token": pair_token,
        "quote": "ETH" if int(pair_token, 16) == 0 else pair_token,
        "launch_config_id": str(int(words[1], 16)),
        "graduation_threshold": str(int(words[2], 16)),
        "launch_block": block_number,
        "launch_tx": log.get("transactionHash"),
        "ts": timestamp,
        "age_s": max(0, int(time.time()) - timestamp),
        "stage": "curve" if record["phase"] == 0 else "pool",
        "venue": "curve" if record["phase"] == 0 else "pool",
        "graduated": record["phase"] != 0,
        "source": "pons_factory_event",
        "price_usd": None,
        "mcap_usd": None,
        "vol1h_usd": None,
        "txns": None,
    }
    if metadata.get("metadata_error"):
        row["metadata_error"] = metadata["metadata_error"]
    return row


def pons_curve_is_tradable(row):
    return row["phase"] == 0 and int(row["pair_token"], 16) == 0


def pons_feed(query, search_term=""):
    try:
        limit = min(200, max(1, int(query.get("limit", "60"))))
        offset = max(0, int(query.get("offset", "0")))
    except ValueError as exc:
        raise ValueError("limit and offset must be integers") from exc
    column = query.get("column", "new")
    if column not in {"new", "bonding", "migrated"}:
        raise ValueError("unsupported Pons feed column")
    with PONS_LAUNCH_CACHE_LOCK:
        if time.time() - PONS_LAUNCH_CACHE["updated_at"] >= 15:
            head = int(rpc_call("eth_blockNumber", []), 16)
            start = max(0, head - max(1, PONS_FEED_WINDOW_BLOCKS))
            logs = pons_launch_logs(start, head)
            ordered_logs = sorted(logs, key=lambda event: int(event["blockNumber"], 16), reverse=True)
            pons_block_timestamps(
                [int(event["blockNumber"], 16) for event in ordered_logs[:200]]
            )
            with ThreadPoolExecutor(max_workers=12) as executor:
                chain_rows = list(executor.map(pons_launch_row, ordered_logs[:200]))
            PONS_LAUNCH_CACHE.update(
                {
                    "updated_at": time.time(),
                    "head": head,
                    "window_start": start,
                    "rows": chain_rows,
                    "scan_truncated": len(ordered_logs) > 200,
                }
            )
        head = PONS_LAUNCH_CACHE["head"]
        start = PONS_LAUNCH_CACHE["window_start"]
        chain_rows = PONS_LAUNCH_CACHE["rows"]
        scan_truncated = PONS_LAUNCH_CACHE["scan_truncated"]
    curve_rows = [row for row in chain_rows if pons_curve_is_tradable(row)]
    if search_term:
        candidates = [
            row
            for row in curve_rows
            if search_term in row["token"].lower()
            or search_term in row["symbol"].lower()
            or search_term in row["name"].lower()
        ]
    elif column == "new":
        candidates = curve_rows
    elif column == "bonding":
        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(enrich_pons_progress, curve_rows))
        candidates = [
            row
            for row in curve_rows
            if row.get("progress") is not None and row["progress"] >= 5
        ]
        if candidates:
            PONS_BONDING_CACHE["updated_at"] = time.time()
            PONS_BONDING_CACHE["rows"] = candidates
        elif PONS_BONDING_CACHE["rows"] and time.time() - PONS_BONDING_CACHE["updated_at"] < 300:
            candidates = PONS_BONDING_CACHE["rows"]
    else:
        candidates = [row for row in chain_rows if row["phase"] != 0]
        if candidates:
            PONS_MIGRATED_CACHE["updated_at"] = time.time()
            PONS_MIGRATED_CACHE["rows"] = candidates
        elif PONS_MIGRATED_CACHE["rows"] and time.time() - PONS_MIGRATED_CACHE["updated_at"] < 300:
            candidates = PONS_MIGRATED_CACHE["rows"]

    page_rows = candidates[offset : offset + limit]
    with ThreadPoolExecutor(max_workers=12) as executor:
        rows = list(executor.map(enrich_pons_row, page_rows))
    return {
        "rows": rows,
        "total": len(candidates),
        "has_more": offset + len(rows) < len(candidates),
        "counts": {column: len(candidates)},
        "head": head,
        "window_start": start,
        "scan_truncated": scan_truncated,
        "source": "pons_chain_rpc",
        "chain_id": CHAIN_ID,
    }


def pons_launch_block(address, head):
    address = address.lower()
    cached = PONS_LAUNCH_BLOCK_CACHE.get(address)
    if cached is not None and time.time() - cached[0] < 60:
        return cached[1]
    start = max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS))
    logs = rpc_call(
        "eth_getLogs",
        [
            {
                "address": PONS_FACTORY,
                "fromBlock": hex(start),
                "toBlock": hex(head),
                "topics": [
                    PONS_LAUNCH_TOPIC,
                    "0x" + address[2:].rjust(64, "0"),
                ],
            }
        ],
    )
    if not isinstance(logs, list):
        raise ValueError("Pons RPC returned an invalid launch-event list")
    block_number = (
        min(int(log["blockNumber"], 16) for log in logs)
        if logs
        else None
    )
    PONS_LAUNCH_BLOCK_CACHE[address] = (time.time(), block_number)
    return block_number


def pons_block_timing(head):
    cached = PONS_BLOCK_RATE_CACHE
    if (
        cached["rate"] is not None
        and time.time() - cached["updated_at"] < 15
        and abs(head - cached["head"]) < 20000
    ):
        return cached["timestamp"], cached["rate"]
    sample = max(0, head - 5000)
    latest = rpc_call("eth_getBlockByNumber", [hex(head), False])
    older = rpc_call("eth_getBlockByNumber", [hex(sample), False])
    if not isinstance(latest, dict) or not isinstance(older, dict):
        raise ValueError("Robinhood Chain RPC did not return block timestamps")
    latest_timestamp = int(latest["timestamp"], 16)
    older_timestamp = int(older["timestamp"], 16)
    elapsed = latest_timestamp - older_timestamp
    if elapsed <= 0 or head <= sample:
        raise ValueError("Robinhood Chain RPC returned an invalid block-time sample")
    rate = (head - sample) / elapsed
    PONS_BLOCK_RATE_CACHE.update(
        {
            "updated_at": time.time(),
            "head": head,
            "timestamp": latest_timestamp,
            "rate": rate,
        }
    )
    return latest_timestamp, rate


def pons_block_at_time(head, timestamp, latest_timestamp=None, rate=None):
    if latest_timestamp is None or rate is None:
        latest_timestamp, rate = pons_block_timing(head)
    blocks_back = max(0, int((latest_timestamp - timestamp) * rate))
    return max(0, min(head, head - blocks_back))


def pons_trade_logs(address, curve, start_block, end_block):
    key = (address.lower(), curve.lower(), start_block, end_block)
    now = time.time()
    with PONS_TRADE_LOG_CACHE_LOCK:
        cached = PONS_TRADE_LOG_CACHE.get(key)
        if cached is not None and now - cached[0] < 3:
            return cached[1]
    query = {
        "address": curve,
        "topics": [[PONS_BUY_TOPIC, PONS_SELL_TOPIC]],
    }
    logs = []
    for batch_start in range(start_block, end_block + 1, 20000):
        batch_end = min(end_block, batch_start + 19999)
        logs.extend(
            pons_index_get_logs(query, batch_start, batch_end)
        )
    with PONS_TRADE_LOG_CACHE_LOCK:
        PONS_TRADE_LOG_CACHE[key] = (now, logs)
        if len(PONS_TRADE_LOG_CACHE) > 256:
            oldest = min(PONS_TRADE_LOG_CACHE, key=lambda cache_key: PONS_TRADE_LOG_CACHE[cache_key][0])
            PONS_TRADE_LOG_CACHE.pop(oldest, None)
    return logs


def pons_decode_trade_log(log, token, decimals, timestamp):
    topics = log.get("topics", [])
    data = log.get("data", "0x")[2:]
    if len(topics) < 3 or len(data) < 128:
        raise ValueError("Pons returned a malformed buy/sell event")
    topic = topics[0].lower()
    if topic not in {PONS_BUY_TOPIC, PONS_SELL_TOPIC}:
        raise ValueError("Pons returned an unsupported trade-event topic")
    first_amount = int(data[:64], 16)
    second_amount = int(data[64:128], 16)
    if first_amount <= 0 or second_amount <= 0:
        raise ValueError("Pons returned a trade event with a zero amount")
    is_buy = topic == PONS_BUY_TOPIC
    token_raw = second_amount if is_buy else first_amount
    eth_raw = first_amount if is_buy else second_amount
    token_amount = Decimal(token_raw) / Decimal(10**decimals)
    eth_amount = Decimal(eth_raw) / Decimal(10**18)
    price_eth = eth_amount / token_amount
    recipient = "0x" + topics[2][-40:]
    actor = "0x" + topics[1][-40:]
    tx_hash = log.get("transactionHash")
    block_number = int(log["blockNumber"], 16)
    log_index = int(log.get("logIndex", "0x0"), 16)
    return {
        "token": token,
        "side": "buy" if is_buy else "sell",
        "type": "buy" if is_buy else "sell",
        "amount": float(eth_amount),
        "tokens": str(token_amount),
        "token_amount": str(token_amount),
        "token_amount_raw": str(token_raw),
        "eth": str(eth_amount),
        "eth_amount": str(eth_amount),
        "eth_amount_raw": str(eth_raw),
        "price": str(price_eth),
        "price_eth": str(price_eth),
        "wallet": recipient,
        "actor": actor,
        "recipient": recipient,
        "maker": recipient,
        "tx": tx_hash,
        "ts": timestamp,
        "block": block_number,
        "idx": log_index,
        "source": "pons_chain_rpc_trade_event",
    }


def pons_parse_trade_logs(logs, token, decimals):
    if not isinstance(decimals, int) or not 0 <= decimals <= 36:
        raise ValueError("Pons token decimals are unavailable; trade history cannot be decoded")
    block_numbers = sorted(
        {
            int(log["blockNumber"], 16)
            for log in logs
            if log.get("topics") and log["topics"][0].lower() in {PONS_BUY_TOPIC, PONS_SELL_TOPIC}
        }
    )
    if not block_numbers:
        return []
    block_times = pons_block_timestamps(block_numbers)
    trades = []
    for log in logs:
        topics = log.get("topics", [])
        if not topics or topics[0].lower() not in {PONS_BUY_TOPIC, PONS_SELL_TOPIC}:
            continue
        trades.append(
            pons_decode_trade_log(
                log,
                token,
                decimals,
                block_times[int(log["blockNumber"], 16)],
            )
        )
    return trades


def pons_index_state():
    with sqlite3.connect(DATABASE) as connection:
        return {
            key: value
            for key, value in connection.execute(
                "SELECT key, value FROM pons_market_index_state"
            )
        }


def pons_set_index_state(**values):
    with sqlite3.connect(DATABASE) as connection:
        connection.executemany(
            "INSERT INTO pons_market_index_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, str(value)) for key, value in values.items()],
        )


def pons_market_index_status():
    try:
        state = pons_index_state()
        head = int(state.get("live_cursor", "0"))
        floor = int(state.get("history_floor", "0"))
        backfill = int(state.get("backfill_next", "0"))
        live_start = int(state.get("live_start", "0"))
        with sqlite3.connect(DATABASE) as connection:
            launches = connection.execute("SELECT COUNT(*) FROM pons_launches").fetchone()[0]
            pools = connection.execute("SELECT COUNT(*) FROM pons_pools").fetchone()[0]
            trades = connection.execute("SELECT COUNT(*) FROM pons_market_trades").fetchone()[0]
        complete = backfill >= max(floor, head - PONS_INDEXER_OVERLAP_BLOCKS)
        updated_at = int(state.get("updated_at", "0"))
        last_error = state.get("last_error")
        running = PONS_INDEXER_THREAD is not None and PONS_INDEXER_THREAD.is_alive()
        return {
            "running": running,
            "healthy": running and updated_at > 0 and time.time() - updated_at <= 30 and not last_error,
            "source": "robinhood_chain_rpc",
            "persistent_worker_required": True,
            "worker_supported": not bool(os.getenv("VERCEL")),
            "deployment_mode": "serverless" if os.getenv("VERCEL") else "persistent",
            "head": head,
            "history_floor": floor,
            "backfill_next": backfill,
            "live_start": live_start,
            "backfill_complete": complete,
            "tokens_indexed": launches,
            "pools_indexed": pools,
            "trades_indexed": trades,
            "updated_at": updated_at,
            "last_error": last_error,
        }
    except (sqlite3.Error, ValueError, TypeError):
        return {
            "running": PONS_INDEXER_THREAD is not None and PONS_INDEXER_THREAD.is_alive(),
            "healthy": False,
            "source": "robinhood_chain_rpc",
            "persistent_worker_required": True,
            "worker_supported": not bool(os.getenv("VERCEL")),
            "deployment_mode": "serverless" if os.getenv("VERCEL") else "persistent",
            "backfill_complete": False,
            "tokens_indexed": 0,
            "pools_indexed": 0,
            "trades_indexed": 0,
        }


def pons_index_get_logs(query, start_block, end_block, min_span=250):
    if start_block > end_block:
        return []
    request = {
        **query,
        "fromBlock": hex(start_block),
        "toBlock": hex(end_block),
    }
    try:
        logs = rpc_call("eth_getLogs", [request])
        if not isinstance(logs, list):
            raise ValueError("Robinhood Chain RPC returned an invalid log list")
        return logs
    except RuntimeError:
        if end_block - start_block < min_span:
            raise
        midpoint = (start_block + end_block) // 2
        return pons_index_get_logs(query, start_block, midpoint, min_span) + pons_index_get_logs(
            query, midpoint + 1, end_block, min_span
        )


def pons_signed_int128(word):
    value = int(word[-32:], 16)
    return value - (1 << 128) if value & (1 << 127) else value


def pons_index_range(start_block, end_block):
    if start_block > end_block:
        return 0

    launch_logs = pons_index_get_logs(
        {"address": PONS_FACTORY, "topics": [PONS_LAUNCH_TOPIC]},
        start_block,
        end_block,
    )
    initialize_logs = pons_index_get_logs(
        {"address": PONS_POOL_MANAGER, "topics": [PONS_V4_INITIALIZE_TOPIC]},
        start_block,
        end_block,
    )

    new_curves = {}
    new_pool_ids = []
    with sqlite3.connect(DATABASE) as connection:
        for log in launch_logs:
            topics = log.get("topics", [])
            data = log.get("data", "0x")[2:]
            if len(topics) < 4 or len(data) < 64:
                continue
            token = "0x" + topics[1][-40:].lower()
            curve = "0x" + topics[2][-40:].lower()
            creator = ("0x" + topics[3][-40:].lower()) if len(topics) >= 4 else None
            pair_token = "0x" + data[:64][-40:].lower()
            launch_block = int(log["blockNumber"], 16)
            existing = connection.execute(
                "SELECT 1 FROM pons_launches WHERE token = ?",
                (token,),
            ).fetchone()
            if existing is None and pair_token == "0x" + "0" * 40:
                new_curves[curve] = launch_block
            connection.execute(
                """INSERT INTO pons_launches(token, curve, pair_token, launch_block, launch_tx, creator)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(token) DO UPDATE SET
                    curve = excluded.curve,
                    pair_token = excluded.pair_token,
                    launch_block = excluded.launch_block,
                    launch_tx = excluded.launch_tx,
                    creator = coalesce(excluded.creator, pons_launches.creator)""",
                (
                    token,
                    curve,
                    pair_token,
                    launch_block,
                    log.get("transactionHash"),
                    creator,
                ),
            )

        for log in initialize_logs:
            topics = log.get("topics", [])
            data = log.get("data", "0x")[2:]
            if len(topics) < 4 or len(data) < 5 * 64:
                continue
            words = [data[index : index + 64] for index in range(0, 5 * 64, 64)]
            hook = "0x" + words[2][-40:].lower()
            if hook != PONS_HOOK:
                continue
            pool_id = topics[1].lower()
            currency0 = "0x" + topics[2][-40:].lower()
            currency1 = "0x" + topics[3][-40:].lower()
            launch = connection.execute(
                "SELECT token, pair_token FROM pons_launches WHERE token IN (?, ?)",
                (currency0, currency1),
            ).fetchone()
            if launch is None:
                continue
            token, pair_token = launch
            token_is_currency0 = token == currency0
            quote_currency = currency1 if token_is_currency0 else currency0
            if quote_currency != pair_token:
                continue
            existing = connection.execute(
                "SELECT 1 FROM pons_pools WHERE pool_id = ?",
                (pool_id,),
            ).fetchone()
            if existing is None:
                new_pool_ids.append(pool_id)
            connection.execute(
                """INSERT INTO pons_pools(
                    pool_id, token, currency0, currency1, token_is_currency0, initialized_block
                ) VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(pool_id) DO UPDATE SET
                    token = excluded.token,
                    currency0 = excluded.currency0,
                    currency1 = excluded.currency1,
                    token_is_currency0 = excluded.token_is_currency0,
                    initialized_block = excluded.initialized_block""",
                (
                    pool_id,
                    token,
                    currency0,
                    currency1,
                    int(token_is_currency0),
                    int(log["blockNumber"], 16),
                ),
            )

        curves = {
            curve: (token, pair_token)
            for token, curve, pair_token in connection.execute(
                "SELECT token, curve, pair_token FROM pons_launches"
            )
            if pair_token == "0x" + "0" * 40
        }
        pools = {
            pool_id: (token, currency0, currency1, bool(token_is_currency0))
            for pool_id, token, currency0, currency1, token_is_currency0 in connection.execute(
                "SELECT pool_id, token, currency0, currency1, token_is_currency0 FROM pons_pools"
            )
        }
        index_state = {
            key: value
            for key, value in connection.execute(
                "SELECT key, value FROM pons_market_index_state"
            )
        }

    curve_logs = pons_index_get_logs(
        {"topics": [[PONS_BUY_TOPIC, PONS_SELL_TOPIC]]},
        start_block,
        end_block,
    )
    catchup_end = max(end_block, int(index_state.get("live_cursor", end_block)))
    if catchup_end > end_block and new_curves:
        new_curve_addresses = list(new_curves)
        for offset in range(0, len(new_curve_addresses), 100):
            curve_logs.extend(
                pons_index_get_logs(
                    {
                        "address": new_curve_addresses[offset : offset + 100],
                        "topics": [[PONS_BUY_TOPIC, PONS_SELL_TOPIC]],
                    },
                    end_block + 1,
                    catchup_end,
                )
            )
    pool_ids = list(pools)
    swap_logs = []
    for offset in range(0, len(pool_ids), 100):
        selected_pool_ids = pool_ids[offset : offset + 100]
        if not selected_pool_ids:
            continue
        swap_logs.extend(
            pons_index_get_logs(
                {
                    "address": PONS_POOL_MANAGER,
                    "topics": [PONS_V4_SWAP_TOPIC, selected_pool_ids],
                },
                start_block,
                end_block,
            )
        )
    if catchup_end > end_block and new_pool_ids:
        for offset in range(0, len(new_pool_ids), 100):
            swap_logs.extend(
                pons_index_get_logs(
                    {
                        "address": PONS_POOL_MANAGER,
                        "topics": [
                            PONS_V4_SWAP_TOPIC,
                            new_pool_ids[offset : offset + 100],
                        ],
                    },
                    end_block + 1,
                    catchup_end,
                )
            )

    prepared = []
    for log in curve_logs:
        topics = log.get("topics", [])
        data = log.get("data", "0x")[2:]
        curve = log.get("address", "").lower()
        launch = curves.get(curve)
        if launch is None or launch[1] != "0x" + "0" * 40:
            continue
        if len(topics) < 3 or len(data) < 128 or topics[0].lower() not in {
            PONS_BUY_TOPIC,
            PONS_SELL_TOPIC,
        }:
            continue
        first_amount = int(data[:64], 16)
        second_amount = int(data[64:128], 16)
        is_buy = topics[0].lower() == PONS_BUY_TOPIC
        quote_raw, token_raw = (
            (first_amount, second_amount) if is_buy else (second_amount, first_amount)
        )
        if quote_raw <= 0 or token_raw <= 0:
            continue
        prepared.append(
            (
                log,
                launch[0],
                "curve",
                None,
                "buy" if is_buy else "sell",
                quote_raw,
                token_raw,
                "0x" + topics[1][-40:].lower(),
                "0x" + topics[2][-40:].lower(),
            )
        )

    for log in swap_logs:
        topics = log.get("topics", [])
        data = log.get("data", "0x")[2:]
        if len(topics) < 3 or len(data) < 128 or topics[0].lower() != PONS_V4_SWAP_TOPIC:
            continue
        pool_id = topics[1].lower()
        pool = pools.get(pool_id)
        if pool is None or "0x" + "0" * 40 not in {pool[1], pool[2]}:
            continue
        amount0 = pons_signed_int128(data[:64])
        amount1 = pons_signed_int128(data[64:128])
        token_delta, quote_delta = (
            (amount0, amount1) if pool[3] else (amount1, amount0)
        )
        if quote_delta > 0 and token_delta < 0:
            side = "buy"
            quote_raw, token_raw = quote_delta, -token_delta
        elif quote_delta < 0 and token_delta > 0:
            side = "sell"
            quote_raw, token_raw = -quote_delta, token_delta
        else:
            continue
        prepared.append(
            (
                log,
                pool[0],
                "v4",
                pool_id,
                side,
                quote_raw,
                token_raw,
                "0x" + topics[2][-40:].lower(),
                None,
            )
        )

    if not prepared:
        return 0

    block_numbers = {
        int(item[0]["blockNumber"], 16)
        for item in prepared
    }
    block_timestamps = pons_block_timestamps(block_numbers)
    rows = []
    for log, token, venue, pool_id, side, quote_raw, token_raw, actor, recipient in prepared:
        tx_hash = log.get("transactionHash")
        if not tx_hash:
            continue
        rows.append(
            (
                tx_hash.lower(),
                int(log.get("logIndex", "0x0"), 16),
                token,
                venue,
                pool_id,
                side,
                str(quote_raw),
                str(token_raw),
                actor,
                recipient,
                int(log["blockNumber"], 16),
                block_timestamps[int(log["blockNumber"], 16)],
            )
        )
    with sqlite3.connect(DATABASE) as connection:
        connection.executemany(
            """INSERT OR IGNORE INTO pons_market_trades(
                tx_hash, log_index, token, venue, pool_id, side, quote_raw, token_raw,
                actor, recipient, block_number, timestamp
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    all_launched_tokens = list({pair[0] for pair in curves.values()})
    transfer_logs = []
    for offset in range(0, len(all_launched_tokens), 100):
        batch = all_launched_tokens[offset : offset + 100]
        if not batch:
            continue
        transfer_logs.extend(
            pons_index_get_logs(
                {"address": batch, "topics": [PONS_TRANSFER_TOPIC]},
                start_block,
                end_block,
            )
        )
    if transfer_logs:
        tf_block_numbers = {int(log["blockNumber"], 16) for log in transfer_logs}
        tf_block_timestamps = pons_block_timestamps(tf_block_numbers)
        transfer_rows = []
        touched_tokens = set()
        for log in transfer_logs:
            topics = log.get("topics", [])
            data = log.get("data", "0x")
            token = log.get("address", "").lower()
            if len(topics) < 3 or not token:
                continue
            src = "0x" + topics[1][-40:].lower()
            dst = "0x" + topics[2][-40:].lower()
            val_raw = str(int(data, 16)) if data != "0x" else "0"
            blk = int(log["blockNumber"], 16)
            ts = tf_block_timestamps.get(blk, 0)
            tx_h = log.get("transactionHash", "").lower()
            log_idx = int(log.get("logIndex", "0x0"), 16)
            transfer_rows.append((tx_h, log_idx, token, src, dst, val_raw, blk, ts))
            touched_tokens.add(token)
        with sqlite3.connect(DATABASE) as connection:
            connection.executemany(
                """INSERT OR IGNORE INTO token_transfers(
                    tx_hash, log_index, token, from_addr, to_addr, amount_raw, block_number, timestamp
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                transfer_rows,
            )
        for tk in touched_tokens:
            try:
                TOKEN_METRICS_EXECUTOR.submit(pons_token_holders_and_metrics, tk, None, False)
            except Exception:
                pass

    return len(rows)


def pons_indexed_trades(address, start_block, end_block):
    address = address.lower()
    with sqlite3.connect(DATABASE) as connection:
        rows = connection.execute(
            """SELECT tx_hash, log_index, venue, pool_id, side, quote_raw, token_raw,
                actor, recipient, block_number, timestamp
            FROM pons_market_trades
            WHERE token = ? AND block_number >= ? AND block_number <= ?
            ORDER BY timestamp, block_number, log_index""",
            (address, int(start_block), int(end_block)),
        ).fetchall()
    metadata = pons_token_metadata(address)
    decimals = metadata.get("decimals")
    if not isinstance(decimals, int) or not 0 <= decimals <= 36:
        raise ValueError("Pons token decimals are unavailable; indexed trades cannot be decoded")
    trades = []
    for tx_hash, log_index, venue, pool_id, side, quote_raw, token_raw, actor, recipient, block, timestamp in rows:
        quote_amount = Decimal(quote_raw) / Decimal(10**18)
        token_amount = Decimal(token_raw) / Decimal(10**decimals)
        if quote_amount <= 0 or token_amount <= 0:
            continue
        price_eth = quote_amount / token_amount
        trades.append(
            {
                "token": address,
                "side": side,
                "type": side,
                "amount": float(quote_amount),
                "tokens": str(token_amount),
                "token_amount": str(token_amount),
                "token_amount_raw": token_raw,
                "eth": str(quote_amount),
                "eth_amount": str(quote_amount),
                "eth_amount_raw": quote_raw,
                "price": str(price_eth),
                "price_eth": str(price_eth),
                "wallet": None if venue == "v4" else recipient or actor,
                "actor": actor,
                "actor_type": "pool_manager_caller" if venue == "v4" else "wallet",
                "recipient": recipient,
                "tx": tx_hash,
                "ts": timestamp,
                "block": block,
                "idx": log_index,
                "venue": venue,
                "pool_id": pool_id,
                "source": "pons_market_indexer",
            }
        )
    return trades


def pons_index_covers(start_block, end_block):
    if start_block > end_block:
        return True
    state = pons_index_state()
    try:
        history_floor = int(state["history_floor"])
        backfill_next = int(state["backfill_next"])
        live_start = int(state["live_start"])
        live_cursor = int(state["live_cursor"])
    except (KeyError, ValueError):
        return False
    if start_block < history_floor or end_block > live_cursor:
        return False
    if end_block < backfill_next:
        return True
    if start_block >= live_start:
        return True
    return backfill_next >= live_start


def pons_indexer_loop():
    init_database()
    while True:
        try:
            with PONS_INDEXER_LOCK:
                head = int(rpc_call("eth_blockNumber", []), 16)
                state = pons_index_state()
                if "live_cursor" not in state:
                    history_floor = max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS))
                    live_start = max(history_floor, head - PONS_INDEXER_OVERLAP_BLOCKS)
                    pons_set_index_state(
                        history_floor=history_floor,
                        backfill_next=history_floor,
                        live_start=live_start,
                        live_cursor=live_start - 1,
                    )
                    state = pons_index_state()

                live_cursor = int(state.get("live_cursor", "0"))
                if live_cursor < head:
                    live_end = min(
                        head,
                        live_cursor + max(1, PONS_INDEXER_CHUNK_BLOCKS),
                    )
                    pons_index_range(live_cursor + 1, live_end)
                    live_cursor = live_end
                    pons_set_index_state(live_cursor=live_cursor)

                backfill_next = int(state.get("backfill_next", state.get("history_floor", "0")))
                backfill_end = live_cursor - PONS_INDEXER_OVERLAP_BLOCKS
                if backfill_next <= backfill_end:
                    end_block = min(
                        backfill_end,
                        backfill_next + max(1, PONS_INDEXER_CHUNK_BLOCKS) - 1,
                    )
                    pons_index_range(backfill_next, end_block)
                    backfill_next = end_block + 1
                    pons_set_index_state(backfill_next=backfill_next)
                pons_set_index_state(updated_at=int(time.time()), last_error="")
        except (
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            sqlite3.Error,
            requests.RequestException,
        ) as exc:
            try:
                pons_set_index_state(updated_at=int(time.time()), last_error=str(exc)[:500])
            except sqlite3.Error:
                pass
            print(f"[pons-indexer] {exc}", flush=True)
        time.sleep(max(0.5, PONS_INDEXER_POLL_SECONDS))


def prewarm_token_metadata(limit=60):
    def _worker():
        try:
            with sqlite3.connect(DATABASE) as conn:
                unfetched = [
                    row[0]
                    for row in conn.execute(
                        """SELECT l.token FROM pons_launches l
                           LEFT JOIN token_meta m ON l.token = m.address
                           WHERE m.address IS NULL
                           ORDER BY l.launch_block DESC
                           LIMIT ?""",
                        (limit,),
                    )
                ]
            for token in unfetched:
                pons_token_metadata_extra(token)
        except Exception:
            pass
    threading.Thread(target=_worker, name="noryx-meta-prewarm", daemon=True).start()


def start_pons_indexer():
    global PONS_INDEXER_THREAD
    prewarm_token_metadata()
    if os.getenv("VERCEL"):
        return
    if PONS_INDEXER_THREAD is not None and PONS_INDEXER_THREAD.is_alive():
        return
    PONS_INDEXER_THREAD = threading.Thread(
        target=pons_indexer_loop,
        name="noryx-pons-market-indexer",
        daemon=True,
    )
    PONS_INDEXER_THREAD.start()


def pons_token_trade_history(address, record, head, start_block, end_block):
    if int(record["pair_token"], 16) != 0:
        raise PonsQuoteError(
            409,
            "unsupported_quote_pair",
            "Pons trade history currently supports ETH-paired tokens only.",
        )
    with sqlite3.connect(DATABASE) as connection:
        indexed_launch = connection.execute(
            "SELECT launch_block FROM pons_launches WHERE token = ?",
            (address.lower(),),
        ).fetchone()
    launch_block = (
        indexed_launch[0]
        if indexed_launch is not None
        else pons_launch_block(address, head)
    )
    history_floor = max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS))
    if launch_block is not None:
        start_block = max(start_block, launch_block)
    start_block = max(start_block, history_floor)
    end_block = min(head, end_block)
    if start_block > end_block:
        return [], launch_block, start_block > (launch_block or 0)
    if pons_index_covers(start_block, end_block):
        trades = pons_indexed_trades(address, start_block, end_block)
        metadata = pons_token_metadata(address)
        decimals = metadata.get("decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 36:
            raise ValueError("Pons token decimals are unavailable; indexed trades cannot be decoded")
        partial = launch_block is None or (
            launch_block < history_floor if launch_block is not None else True
        )
        return trades, launch_block, partial
    logs = pons_trade_logs(address, record["curve"], start_block, end_block)
    metadata = pons_token_metadata(address)
    trades = pons_parse_trade_logs(logs, address, metadata.get("decimals"))
    partial = launch_block is None or record["phase"] != 0 or (
        launch_block < history_floor if launch_block is not None else True
    )
    return trades, launch_block, partial


def pons_trade_flow(address, record=None):
    record = record or pons_factory_record(address)
    if record is None:
        raise PonsQuoteError(404, "not_a_pons_token", "This token is not registered by the Pons factory.")
    head = int(rpc_call("eth_blockNumber", []), 16)
    latest_timestamp, rate = pons_block_timing(head)
    seconds = 86400
    start_timestamp = latest_timestamp - seconds
    estimated_start = pons_block_at_time(head, start_timestamp, latest_timestamp, rate)
    start_block = max(0, estimated_start - int(rate * 10))
    trades, launch_block, partial = pons_token_trade_history(
        address, record, head, start_block, head
    )
    indexed_history = pons_index_covers(
        max(
            start_block,
            launch_block or 0,
            max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS)),
        ),
        head,
    )
    trades.sort(key=lambda trade: (trade["ts"], trade["block"], trade["idx"]))
    eth_usd = Decimal(str(eth_usd_price()))
    windows = {}
    changes = {}
    for name, duration in (("5m", 300), ("1h", 3600), ("6h", 21600), ("24h", 86400)):
        selected = [trade for trade in trades if trade["ts"] >= latest_timestamp - duration]
        buys = [trade for trade in selected if trade["side"] == "buy"]
        sells = [trade for trade in selected if trade["side"] == "sell"]
        buy_usd = sum(Decimal(trade["eth"]) * eth_usd for trade in buys)
        sell_usd = sum(Decimal(trade["eth"]) * eth_usd for trade in sells)
        prices = [Decimal(trade["price_eth"]) for trade in selected]
        change = (
            float((prices[-1] / prices[0] - 1) * 100)
            if len(prices) > 1 and prices[0] > 0
            else None
        )
        windows[name] = {
            "vol_usd": float(buy_usd + sell_usd),
            "buy_usd": float(buy_usd),
            "sell_usd": float(sell_usd),
            "net_usd": float(buy_usd - sell_usd),
            "buys": len(buys),
            "sells": len(sells),
            "n": len(selected),
        }
        changes[name] = change
    recent_trades = sorted(trades, key=lambda trade: (trade["ts"], trade["block"], trade["idx"]), reverse=True)
    return {
        "address": address,
        "w": windows,
        "chg": changes,
        "trades": recent_trades[:200],
        "deep": True,
        "partial": partial,
        "launch_block": launch_block,
        "window_start": start_timestamp,
        "head": head,
        "coverage": (
            "Indexed Pons launch-curve and Robinhood v4 pool swap events."
            if indexed_history
            else "Pons launch-curve swap events; migrated pool swaps may be missing while the index catches up."
        ),
        "source": (
            "pons_market_indexer"
            if indexed_history
            else "pons_curve_trade_events"
        ),
        "read_only": True,
    }


def pons_token_trades(address, query):
    try:
        limit = min(200, max(1, int(query.get("limit", "100"))))
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    flow = pons_trade_flow(address)
    trades = flow["trades"]
    total = flow["w"]["24h"]["n"]
    return {
        "address": address,
        "trades": trades[:limit],
        "total": total,
        "has_more": total > limit or flow["partial"],
        "partial": flow["partial"],
        "head": flow["head"],
        "coverage": flow["coverage"],
        "source": flow["source"],
        "read_only": True,
    }


def pons_token_candles(address, query):
    record = pons_factory_record(address)
    if record is None:
        raise PonsQuoteError(404, "not_a_pons_token", "This token is not registered by the Pons factory.")
    durations = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    timeframe = query.get("tf", "15m")
    if timeframe not in durations:
        raise ValueError("Unsupported candle timeframe")
    interval = durations[timeframe]
    head = int(rpc_call("eth_blockNumber", []), 16)
    latest_timestamp, rate = pons_block_timing(head)
    try:
        end_timestamp = min(latest_timestamp, int(query.get("before", latest_timestamp + 1)))
    except ValueError as exc:
        raise ValueError("before must be a Unix timestamp in seconds") from exc
    if end_timestamp <= 0:
        raise ValueError("before must be a positive Unix timestamp")
    start_timestamp = end_timestamp - interval * 300
    start_block = pons_block_at_time(head, start_timestamp, latest_timestamp, rate)
    end_block = pons_block_at_time(head, end_timestamp, latest_timestamp, rate)
    trades, launch_block, partial = pons_token_trade_history(
        address, record, head, start_block - int(rate * 10), end_block
    )
    indexed_history = pons_index_covers(
        max(
            start_block - int(rate * 10),
            launch_block or 0,
            max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS)),
        ),
        min(head, end_block),
    )
    selected = [
        trade
        for trade in trades
        if start_timestamp <= trade["ts"] < end_timestamp
    ]
    candles_by_time = {}
    for trade in sorted(selected, key=lambda item: (item["ts"], item["block"], item["idx"])):
        candle_time = trade["ts"] // interval * interval
        price = float(trade["price_eth"])
        candle = candles_by_time.get(candle_time)
        if candle is None:
            candles_by_time[candle_time] = {
                "t": candle_time,
                "o": price,
                "h": price,
                "l": price,
                "c": price,
                "v": trade["amount"],
                "token_volume": float(trade["token_amount"]),
                "trades": 1,
            }
        else:
            candle["h"] = max(candle["h"], price)
            candle["l"] = min(candle["l"], price)
            candle["c"] = price
            candle["v"] += trade["amount"]
            candle["token_volume"] += float(trade["token_amount"])
            candle["trades"] += 1
    return {
        "address": address,
        "candles": [candles_by_time[key] for key in sorted(candles_by_time)],
        "quote": "ETH",
        "tf": timeframe,
        "supply": None,
        "before": end_timestamp,
        "partial": partial,
        "launch_block": launch_block,
        "coverage": (
            "Indexed Pons launch-curve and Robinhood v4 pool swap events."
            if indexed_history
            else "Pons launch-curve swap events; migrated pool swaps may be missing while the index catches up."
        ),
        "source": (
            "pons_market_indexer"
            if indexed_history
            else "pons_curve_trade_events"
        ),
        "read_only": True,
    }


def pons_trend_launches(head):
    with PONS_TREND_LAUNCH_CACHE_LOCK:
        return _pons_trend_launches_cached(head)


def _pons_trend_launches_cached(head):
    cached = PONS_TREND_LAUNCH_CACHE
    start = max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS))

    def add_logs(by_curve, logs):
        for log in logs:
            topics = log.get("topics", [])
            data = log.get("data", "0x")[2:]
            if len(topics) < 4 or len(data) < 64:
                raise ValueError("Pons factory returned a malformed TokenLaunched event")
            pair_word = data[:64]
            if pair_word[:24] != "0" * 24 or int(pair_word, 16) != 0:
                continue
            token = "0x" + topics[1][-40:].lower()
            curve = "0x" + topics[2][-40:].lower()
            by_curve[curve] = {
                "token": token,
                "launch_block": int(log["blockNumber"], 16),
            }

    if (
        cached["by_curve"]
        and time.time() - cached["updated_at"] < 300
        and cached["head"] <= head
        and head - cached["head"] < max(1, PONS_HISTORY_MAX_BLOCKS)
    ):
        if head > cached["head"]:
            add_logs(cached["by_curve"], pons_launch_logs(cached["head"] + 1, head))
            cached["head"] = head
        cached["updated_at"] = time.time()
        return cached["by_curve"], start
    by_curve = {}
    add_logs(by_curve, pons_launch_logs(start, head))
    PONS_TREND_LAUNCH_CACHE.update(
        {"updated_at": time.time(), "head": head, "by_curve": by_curve}
    )
    return by_curve, start


def pons_global_trade_logs(start_block, end_block):
    ranges = [
        (start, min(end_block, start + 19999))
        for start in range(start_block, end_block + 1, 20000)
    ]
    if not ranges:
        return []

    def fetch(block_range):
        start, end = block_range
        logs = rpc_call(
            "eth_getLogs",
            [
                {
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                    "topics": [[PONS_BUY_TOPIC, PONS_SELL_TOPIC]],
                }
            ],
        )
        if not isinstance(logs, list):
            raise ValueError("Pons RPC returned an invalid global trade-event list")
        return logs

    with ThreadPoolExecutor(max_workers=2) as executor:
        batches = list(executor.map(fetch, ranges))
    return [log for batch in batches for log in batch]


def pons_trending(query):
    window = query.get("window", "1h")
    seconds_by_window = {"5m": 300, "1h": 3600, "6h": 21600, "24h": 86400}
    if window not in seconds_by_window:
        raise ValueError("Unsupported trending window")
    sort = query.get("sort", "volume")
    if sort not in {"volume", "gainers", "losers", "txns"}:
        raise ValueError("Unsupported trending sort")
    try:
        limit = min(50, max(1, int(query.get("limit", "50"))))
    except ValueError as exc:
        raise ValueError("limit must be an integer") from exc
    cache_key = (window, sort, limit)
    cached = PONS_TREND_CACHE.get(cache_key)
    if cached is not None and time.time() - cached[0] < 12:
        return cached[1]

    head = int(rpc_call("eth_blockNumber", []), 16)
    latest_timestamp, rate = pons_block_timing(head)
    window_seconds = seconds_by_window[window]
    start_timestamp = latest_timestamp - window_seconds
    estimated_start = pons_block_at_time(head, start_timestamp, latest_timestamp, rate)
    history_floor = max(0, head - max(1, PONS_HISTORY_MAX_BLOCKS))
    boundary_seconds = max(60, min(600, int(window_seconds * 0.02)))
    start_block = max(
        history_floor,
        estimated_start - int(rate * (boundary_seconds + 20)),
    )
    grouped = {}
    indexed_history = pons_index_covers(start_block, head)

    def add_trade(token, curve, launch_block, side, quote_raw, token_raw, timestamp, block, idx):
        if timestamp < start_timestamp or quote_raw <= 0 or token_raw <= 0:
            return
        is_buy = side == "buy"
        normalized_price = Decimal(quote_raw) / Decimal(token_raw)
        group = grouped.setdefault(
            token,
            {
                "curve": curve,
                "launch_block": launch_block,
                "trades": [],
                "volume_eth": Decimal("0"),
                "buys": 0,
                "sells": 0,
            },
        )
        group["trades"].append(
            {
                "buy": is_buy,
                "eth_raw": quote_raw,
                "token_raw": token_raw,
                "normalized_price": normalized_price,
                "timestamp": timestamp,
                "block": block,
                "idx": idx,
            }
        )
        group["volume_eth"] += Decimal(quote_raw) / Decimal(10**18)
        group["buys" if is_buy else "sells"] += 1

    if indexed_history:
        index_state = pons_index_state()
        launch_floor = int(index_state.get("history_floor", history_floor))
        with sqlite3.connect(DATABASE) as connection:
            launches_by_token = {
                token: (curve, launch_block)
                for token, curve, launch_block in connection.execute(
                    "SELECT token, curve, launch_block FROM pons_launches"
                )
            }
            indexed_rows = connection.execute(
                """SELECT token, side, quote_raw, token_raw, block_number, timestamp, log_index
                FROM pons_market_trades
                WHERE block_number >= ? AND block_number <= ?
                ORDER BY timestamp, block_number, log_index""",
                (start_block, head),
            ).fetchall()
        for token, side, quote_raw, token_raw, block, timestamp, idx in indexed_rows:
            launch = launches_by_token.get(token)
            if launch is None:
                continue
            add_trade(
                token,
                launch[0],
                launch[1],
                side,
                int(quote_raw),
                int(token_raw),
                timestamp,
                block,
                idx,
            )
    else:
        launches, launch_floor = pons_trend_launches(head)
        logs = pons_global_trade_logs(start_block, head)
        block_numbers = sorted(
            {
                int(log["blockNumber"], 16)
                for log in logs
                if log.get("topics")
                and log["topics"][0].lower() in {PONS_BUY_TOPIC, PONS_SELL_TOPIC}
            }
        )
        estimated_timestamps = {
            block_number: latest_timestamp - int((head - block_number) / rate)
            for block_number in block_numbers
        }
        exact_boundary_blocks = [
            block_number
            for block_number, timestamp in estimated_timestamps.items()
            if abs(timestamp - start_timestamp) <= boundary_seconds
            or latest_timestamp - timestamp <= 10
        ]
        timestamps = estimated_timestamps
        timestamps.update(pons_block_timestamps(exact_boundary_blocks))
        for log in logs:
            topics = log.get("topics", [])
            if not topics or topics[0].lower() not in {PONS_BUY_TOPIC, PONS_SELL_TOPIC}:
                continue
            curve = log.get("address", "").lower()
            launch = launches.get(curve)
            block_number = int(log["blockNumber"], 16)
            timestamp = timestamps[block_number]
            if launch is None:
                continue
            data = log.get("data", "0x")[2:]
            if len(data) < 128:
                raise ValueError("Pons returned a malformed buy/sell event")
            is_buy = topics[0].lower() == PONS_BUY_TOPIC
            first_amount = int(data[:64], 16)
            second_amount = int(data[64:128], 16)
            token_raw = second_amount if is_buy else first_amount
            quote_raw = first_amount if is_buy else second_amount
            add_trade(
                launch["token"],
                curve,
                launch["launch_block"],
                "buy" if is_buy else "sell",
                quote_raw,
                token_raw,
                timestamp,
                block_number,
                int(log.get("logIndex", "0x0"), 16),
            )

    eth_usd = Decimal(str(eth_usd_price()))
    candidates = []
    for token, group in grouped.items():
        events = sorted(group["trades"], key=lambda trade: (trade["timestamp"], trade["block"], trade["idx"]))
        change = (
            float((events[-1]["normalized_price"] / events[0]["normalized_price"] - 1) * 100)
            if len(events) > 1 and events[0]["normalized_price"] > 0
            else None
        )
        candidates.append(
            {
                "token": token,
                "curve": group["curve"],
                "launch_block": group["launch_block"],
                "events": events,
                "buys": group["buys"],
                "sells": group["sells"],
                "txns": len(events),
                "vol_usd": float(group["volume_eth"] * eth_usd),
                "chg_pct": change,
            }
        )
    order = {
        "volume": lambda item: -item["vol_usd"],
        "gainers": lambda item: -(item["chg_pct"] if item["chg_pct"] is not None else -1e9),
        "losers": lambda item: item["chg_pct"] if item["chg_pct"] is not None else 1e9,
        "txns": lambda item: -item["txns"],
    }[sort]
    candidates.sort(key=order)
    selected = candidates[:limit]
    tokens = [item["token"] for item in selected]
    with ThreadPoolExecutor(max_workers=min(12, len(tokens) or 1)) as executor:
        token_info_rows = list(executor.map(pons_trend_token_info, tokens))
    rows = []
    for item, (metadata, supply_raw, supply_error) in zip(selected, token_info_rows):
        decimals = metadata.get("decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 36:
            continue
        latest_trade = item["events"][-1]
        price_eth = (
            Decimal(latest_trade["eth_raw"])
            / Decimal(10**18)
            / (Decimal(latest_trade["token_raw"]) / Decimal(10**decimals))
        )
        price_usd = price_eth * eth_usd
        supply = (
            Decimal(supply_raw) / Decimal(10**decimals)
            if supply_raw is not None
            else None
        )
        meta_extra = pons_token_metadata_extra(item["token"])
        rows.append(
            {
                "token": item["token"],
                "name": metadata.get("name", ""),
                "symbol": metadata.get("symbol", ""),
                "image": meta_extra.get("image"),
                "x_url": meta_extra.get("x_url"),
                "x_handle": meta_extra.get("x_handle"),
                "tg_url": meta_extra.get("tg_url"),
                "site": meta_extra.get("site"),
                "description": meta_extra.get("description"),
                "price_eth": str(price_eth),
                "price_usd": str(price_usd),
                "supply": str(supply) if supply is not None else None,
                "mcap_usd": str(price_usd * supply) if supply is not None else None,
                "mcap_error": supply_error,
                "price_method": (
                    "last_verified_pons_trade"
                    if indexed_history
                    else "last_verified_curve_trade"
                ),
                "mcap_method": (
                    "last_verified_pons_trade_x_total_supply"
                    if indexed_history
                    else "last_verified_curve_trade_x_total_supply"
                ),
                "last_trade_ts": latest_trade["timestamp"],
                "chg_pct": item["chg_pct"],
                "vol_usd": item["vol_usd"],
                "buys": item["buys"],
                "sells": item["sells"],
                "txns": item["txns"],
                "thin": False,
                "source": (
                    "pons_market_indexer"
                    if indexed_history
                    else "pons_curve_trade_events"
                ),
            }
        )
    result = {
        "rows": rows,
        "total": len(candidates),
        "thin_excluded": 0,
        "window": window,
        "sort": sort,
        "partial": (
            not indexed_history
            or (start_block <= launch_floor and start_block > 0)
        ),
        "volume_usd_total": sum(item["vol_usd"] for item in candidates),
        "head": head,
        "window_start": start_timestamp,
        "timestamp_method": (
            "exact Robinhood Chain block timestamps"
            if indexed_history
            else "block-rate estimate; exact timestamps at window boundaries"
        ),
        "coverage": (
            "Indexed Pons launch-curve and Robinhood v4 pool swap events."
            if indexed_history
            else "Pons launch-curve swap events; migrated pool swaps may be missing while the index catches up."
        ),
        "source": (
            "pons_market_indexer"
            if indexed_history
            else "pons_curve_trade_events"
        ),
        "chain_id": CHAIN_ID,
        "read_only": True,
    }
    PONS_TREND_CACHE[cache_key] = (time.time(), result)
    return result


class PonsQuoteError(Exception):
    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status = status
        self.code = code


def decimal_units(raw, decimals):
    scale = 10**decimals
    whole, fraction = divmod(raw, scale)
    if not fraction:
        return str(whole)
    return f"{whole}.{str(fraction).zfill(decimals).rstrip('0')}"


def pons_estimate_gas(call, fallback):
    try:
        result = rpc_call("eth_estimateGas", [call])
        if isinstance(result, str) and result.startswith("0x"):
            gas = int(result, 16)
            if gas > 21000:
                return hex(int(gas * 1.3))
    except (RuntimeError, ValueError, TypeError, requests.RequestException):
        pass
    return hex(fallback)


def pons_allowance_storage_slot(owner, spender):
    try:
        owner_slot = rpc_call(
            "web3_sha3",
            ["0x" + owner[2:].rjust(64, "0") + f"{1:064x}"],
        )
        return rpc_call(
            "web3_sha3",
            ["0x" + spender[2:].rjust(64, "0") + owner_slot[2:]],
        )
    except (RuntimeError, requests.RequestException, ValueError, TypeError):
        if crypto_keccak is None:
            raise PonsQuoteError(503, "quota_storage_unavailable", "Allowance storage slot could not be computed without RPC hash support.")
        def hash_word_data(data):
            h = crypto_keccak.new(digest_bits=256)
            h.update(bytes.fromhex(data))
            return h.hexdigest()
        owner_slot = hash_word_data(owner[2:].rjust(64, "0") + f"{1:064x}")
        return "0x" + hash_word_data(spender[2:].rjust(64, "0") + owner_slot.rjust(64, "0"))


def _abi_word(value):
    return f"{int(value):064x}"


def _abi_address(address):
    return address[2:].lower().rjust(64, "0")


def _abi_bytes(value):
    raw = value.lower().replace("0x", "")
    length = len(raw) // 2
    padded = raw + "0" * ((32 - length % 32) * 2 if length % 32 else 0)
    return _abi_word(length) + padded


def pons_v4_quote(query, record):
    token = query["tok"].lower()
    owner = query["owner"].lower() if query.get("owner") else "0x0000000000000000000000000000000000000001"
    side = query["side"]
    preview_only = not query.get("owner")
    try:
        slippage = Decimal(query.get("slippage", "5"))
        if not slippage.is_finite() or slippage < 0 or slippage > 30 or slippage * 100 != int(slippage * 100):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise PonsQuoteError(400, "invalid_slippage", "Slippage must be between 0 and 30%, with at most two decimal places.")
    slippage_bps = int(slippage * 100)
    metadata = pons_token_metadata(token)
    decimals = metadata.get("decimals")
    if not isinstance(decimals, int) or decimals < 0 or decimals > 36:
        raise PonsQuoteError(503, "token_metadata_unavailable", "Pons token decimals could not be read from chain.")

    if side == "buy":
        try:
            amount_in = int(query.get("wei", "0"))
        except ValueError as exc:
            raise PonsQuoteError(400, "invalid_amount", "Buy amount in wei must be an integer.") from exc
        if amount_in <= 0:
            raise PonsQuoteError(400, "invalid_amount", "Buy amount must be greater than zero.")
        value, output_decimals, wrapped = amount_in, decimals, True
    else:
        try:
            pct = Decimal(query.get("pct", "0"))
            if not pct.is_finite() or pct <= 0 or pct > 100 or pct * 100 != int(pct * 100):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise PonsQuoteError(400, "invalid_amount", "Sell percentage must be greater than 0 and no more than 100.")
        balance = int(rpc_call("eth_call", [{"to": token, "data": "0x70a08231" + owner[2:].rjust(64, "0")}, "latest"]), 16)
        amount_in = balance * int(pct * 100) // 10000
        if amount_in <= 0:
            raise PonsQuoteError(409, "no_token_balance", "This wallet has no Pons token balance to sell.")
        value, output_decimals, wrapped = 0, 18, False

    currency0 = PONS_WETH if int(PONS_WETH, 16) < int(token, 16) else token
    currency1 = token if currency0 == PONS_WETH else PONS_WETH
    zero_for_one = 1 if currency0 == PONS_WETH else 0
    tick_spacing = int(record.get("tick_spacing") or 0)
    deadline = int(time.time()) + 30 * 60
    expiry = int(time.time()) + 31 * 86400

    key = (
        _abi_address(currency0) + _abi_address(currency1) + _abi_word(0)
        + _abi_word(tick_spacing & ((1 << 24) - 1)) + _abi_address(PONS_HOOK)
    )
    swap_params = key + _abi_word(zero_for_one) + _abi_word(amount_in) + _abi_word(0) + _abi_word(160) + _abi_word(0)
    settle_params = (
        _abi_address(PONS_WETH) + _abi_word(amount_in) + _abi_word(0)
        if wrapped else
        _abi_address(token) + _abi_word(amount_in)
    )
    take_params = (
        _abi_address(token) + _abi_word(0)
        if side == "buy" else
        _abi_address(PONS_WETH) + _abi_word(0)
    )
    actions = "0b060f" if wrapped else "060c0f"
    plan = _abi_bytes(actions) + _abi_word(96) + _abi_word(160) + _abi_word(224)
    plan += _abi_bytes(swap_params) + _abi_bytes(settle_params) + _abi_bytes(take_params)
    input_data = plan
    if wrapped:
        wrap_input = _abi_address("0x0000000000000000000000000000000000000002") + _abi_word(amount_in)
        inputs = [_abi_bytes(wrap_input), _abi_bytes(input_data)]
    else:
        inputs = [_abi_bytes(input_data)]

    commands = "0b10" if wrapped else "10"
    inputs_head = _abi_word(len(inputs))
    offsets = []
    cursor = len(inputs) * 32 + 32
    for item in inputs:
        offsets.append(_abi_word(cursor))
        cursor += len(item) // 2
    execute_tail = _abi_word(len(commands) // 2) + bytes.fromhex(commands).hex().ljust(64, "0") if False else ""
    execute_head = _abi_word(96) + _abi_word(160 if wrapped else 128) + _abi_word(deadline)
    execute_body = (
        _abi_bytes(commands)
        + inputs_head + "".join(offsets) + "".join(inputs)
    )
    execute_data = "0x3593564c" + execute_head[0:0] + _abi_word(96) + _abi_word(160 if wrapped else 128) + _abi_word(deadline) + execute_body

    # Try a configured official quoter or simulate the exact UR calldata for output discovery.
    out_raw = 0
    quoter = os.getenv("NORYX_V4_QUOTER", "").strip().lower()
    if re.fullmatch(r"0x[0-9a-f]{40}", quoter):
        try:
            quoter_result = rpc_call("eth_call", [{"to": quoter, "data": execute_data, "from": owner, "value": hex(value)}, "latest"])
            if isinstance(quoter_result, str) and len(quoter_result) >= 66:
                out_raw = int(quoter_result[-64:], 16)
        except (RuntimeError, requests.RequestException, ValueError, TypeError):
            pass
    if out_raw <= 0:
        try:
            simulated = rpc_call("eth_call", [{"to": PONS_UNIVERSAL_ROUTER, "from": owner, "data": execute_data, "value": hex(value)}, "latest"])
            if isinstance(simulated, str) and len(simulated) >= 66:
                out_raw = int(simulated[-64:], 16)
        except (RuntimeError, requests.RequestException, ValueError, TypeError):
            pass
    if out_raw <= 0:
        raise PonsQuoteError(503, "v4_quote_unavailable", "No verified Uniswap v4 Quoter is configured and the pool output could not be simulated.")
    min_out_raw = max(1, out_raw * (10000 - slippage_bps) // 10000)
    calls = []
    if side == "sell" and not preview_only:
        allowance = int(rpc_call("eth_call", [{"to": token, "data": "0xdd62ed3e" + owner[2:].rjust(64, "0") + PONS_PERMIT2[2:].rjust(64, "0")}, "latest"]), 16)
        if allowance < amount_in:
            approval = "0x095ea7b3" + PONS_PERMIT2[2:].rjust(64, "0") + f"{amount_in:064x}"
            approval_call = {"to": token, "data": approval, "value": "0x0", "label": "Approve Permit2", "gas": None}
            approval_call["gas"] = pons_estimate_gas(approval_call, 90000)
            calls.append(approval_call)
        p2 = "0x87517c45" + PONS_UNIVERSAL_ROUTER[2:].rjust(64, "0") + f"{amount_in:064x}" + f"{expiry:064x}"
        p2_call = {"to": PONS_PERMIT2, "data": p2, "value": "0x0", "label": "Approve Universal Router in Permit2", "gas": None}
        p2_call["gas"] = pons_estimate_gas(p2_call, 90000)
        calls.append(p2_call)
    trade_call = {"to": PONS_UNIVERSAL_ROUTER, "data": execute_data, "value": hex(value), "label": "Buy" if side == "buy" else "Sell", "gas": None}
    trade_call["gas"] = pons_estimate_gas(trade_call, 300000)
    calls.append(trade_call)
    pool_id_words = (
        _abi_address(currency0)
        + _abi_address(currency1)
        + _abi_word(0)
        + _abi_word(tick_spacing & ((1 << 24) - 1))
        + _abi_address(PONS_HOOK)
    )
    if crypto_keccak is not None:
        h = crypto_keccak.new(digest_bits=256)
        h.update(bytes.fromhex(pool_id_words))
        pool_id = "0x" + h.hexdigest()
    else:
        pool_id = None
    pool = {"id": pool_id, "address": None, "fee": 0, "tickSpacing": tick_spacing, "hooks": PONS_HOOK}
    return {
        "token": token, "side": side, "venue": "v4", "launchpad": "pons",
        "route": {"venue": "v4", "launchpad": "pons", "pool": pool},
        "pair": {"address": "0x0", "symbol": "ETH", "class": "native"},
        "quote": "ETH", "receive": (metadata.get("symbol") or token) if side == "buy" else "ETH",
        "amount_in": decimal_units(amount_in, 18 if side == "buy" else decimals),
        "out": decimal_units(out_raw, output_decimals),
        "min_out": decimal_units(min_out_raw, output_decimals),
        "out_raw": str(out_raw), "min_out_raw": str(min_out_raw),
        "slippage": str(slippage), "source": "pons_v4_pool_simulation",
        "preview_only": preview_only, "calls": calls,
    }

def pons_curve_quote(query):
    token = query.get("tok", "").lower()
    owner = query.get("owner", "").lower()
    side = query.get("side", "")
    preview_only = not owner and side == "buy"
    if preview_only:
        owner = "0x0000000000000000000000000000000000000001"
    if not re.fullmatch(r"0x[0-9a-f]{40}", token) or not re.fullmatch(r"0x[0-9a-f]{40}", owner):
        raise PonsQuoteError(400, "invalid_quote_request", "A valid token and wallet address are required.")
    if side not in {"buy", "sell"}:
        raise PonsQuoteError(400, "invalid_quote_request", "Trade side must be buy or sell.")

    record = pons_factory_record(token)
    if record is None:
        raise PonsQuoteError(404, "not_a_pons_token", "This token is not registered by the Pons factory.")
    if record["phase"] == 1:
        raise PonsQuoteError(409, "pons_launch_transition", "This Pons token is transitioning between launch curve and pool. Try again when its phase is final.")
    if record["phase"] != 0 and record["phase"] != 2:
        raise PonsQuoteError(409, "pons_curve_closed", "This Pons token is not available for launch-curve or v4 pool trading.")
    if record["phase"] == 2:
        return pons_v4_quote(query, record)
    curve = record["curve"]
    pair = record["pair_token"]
    if int(pair, 16) != 0:
        raise PonsQuoteError(409, "pons_pair_not_supported", "Direct Pons quotes currently support ETH-paired launch curves only.")

    try:
        slippage = Decimal(query.get("slippage", "5"))
        if not slippage.is_finite() or slippage < 0 or slippage > 30 or slippage * 100 != int(slippage * 100):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise PonsQuoteError(400, "invalid_slippage", "Slippage must be between 0 and 30%, with at most two decimal places.")
    slippage_bps = int(slippage * 100)

    token_metadata = pons_token_metadata(token)
    token_decimals = token_metadata.get("decimals")
    if not isinstance(token_decimals, int) or token_decimals < 0 or token_decimals > 36:
        raise PonsQuoteError(503, "token_metadata_unavailable", "Pons token decimals could not be read from chain.")

    if side == "buy":
        try:
            amount_in = int(query.get("wei", "0"))
        except ValueError as exc:
            raise PonsQuoteError(400, "invalid_amount", "Buy amount in wei must be an integer.") from exc
        if amount_in <= 0:
            raise PonsQuoteError(400, "invalid_amount", "Buy amount must be greater than zero.")
        selector = "59a87bc1"
        value = amount_in
        output_decimals = token_decimals
    else:
        try:
            pct = Decimal(query.get("pct", "0"))
            if not pct.is_finite() or pct <= 0 or pct > 100 or pct * 100 != int(pct * 100):
                raise ValueError
        except (InvalidOperation, ValueError):
            raise PonsQuoteError(400, "invalid_amount", "Sell percentage must be greater than 0 and no more than 100.")
        balance_data = "0x70a08231" + owner[2:].rjust(64, "0")
        balance = int(rpc_call("eth_call", [{"to": token, "data": balance_data}, "latest"]), 16)
        amount_in = balance * int(pct * 100) // 10000
        if amount_in <= 0:
            raise PonsQuoteError(409, "no_token_balance", "This wallet has no Pons token balance to sell.")
        selector = "d04c6983"
        value = 0
        output_decimals = 18
        allowance_data = (
            "0xdd62ed3e"
            + owner[2:].rjust(64, "0")
            + curve[2:].rjust(64, "0")
        )
        allowance = int(
            rpc_call("eth_call", [{"to": token, "data": allowance_data}, "latest"]),
            16,
        )
        if allowance < amount_in:
            approval_data = (
                "0x095ea7b3"
                + curve[2:].rjust(64, "0")
                + f"{amount_in:064x}"
            )
            approval_call = {
                "to": token,
                "data": approval_data,
                "value": "0x0",
                "label": "Approve sale",
            }
            approval_call["gas"] = pons_estimate_gas(approval_call, 90000)
        else:
            approval_call = None

    call_data = (
        "0x"
        + selector
        + f"{amount_in:064x}"
        + f"{0:064x}"
        + owner[2:].rjust(64, "0")
    )
    eth_call_params = [
        {"to": curve, "from": owner, "data": call_data, "value": hex(value)},
        "latest",
    ]
    if side == "sell" and approval_call:
        # Pons ERC-20 contracts store allowances in mapping slot 1; override it only for this read-only quote.
        storage_slot = pons_allowance_storage_slot(owner, curve)
        eth_call_params.append(
            {
                token: {
                    "stateDiff": {
                        storage_slot: f"0x{amount_in:064x}",
                    }
                }
            }
        )
    try:
        result = rpc_call("eth_call", eth_call_params)
    except RuntimeError as exc:
        detail = str(exc)
        if "revert" in detail.lower():
            raise PonsQuoteError(409, "quote_rejected", detail) from exc
        if detail.startswith("All RPC endpoints failed:"):
            raise PonsQuoteError(503, "pons_rpc_unavailable", detail) from exc
        raise PonsQuoteError(409, "quote_rejected", detail) from exc
    if not isinstance(result, str) or len(result) < 66:
        raise PonsQuoteError(503, "invalid_pons_quote", "The Pons curve did not return an output amount.")
    out_raw = int(result, 16)
    if out_raw <= 0:
        raise PonsQuoteError(409, "no_route", "The Pons curve returned zero output for this trade.")
    min_out_raw = max(1, out_raw * (10000 - slippage_bps) // 10000)
    call_data = (
        "0x"
        + selector
        + f"{amount_in:064x}"
        + f"{min_out_raw:064x}"
        + owner[2:].rjust(64, "0")
    )
    calls = []
    if not preview_only:
        if side == "sell" and approval_call:
            calls.append(approval_call)
        calls.append(
            {
                "to": curve,
                "data": call_data,
                "value": hex(value),
                "label": "Buy" if side == "buy" else "Sell",
            }
        )
    for call in calls:
        if "gas" not in call:
            fallback = 90000 if str(call.get("label", "")).lower().startswith("approve") else 300000
            call["gas"] = pons_estimate_gas(call, fallback)
    return {
        "token": token,
        "side": side,
        "venue": "curve",
        "launchpad": "pons",
        "route": {"venue": "curve", "launchpad": "pons", "pool": None},
        "pair": {"address": pair, "symbol": "ETH", "class": "native"},
        "quote": "ETH",
        "receive": (token_metadata.get("symbol") or token) if side == "buy" else "ETH",
        "amount_in": decimal_units(amount_in, 18 if side == "buy" else token_decimals),
        "out": decimal_units(out_raw, output_decimals),
        "min_out": decimal_units(min_out_raw, output_decimals),
        "out_raw": str(out_raw),
        "min_out_raw": str(min_out_raw),
        "slippage": str(slippage),
        "source": "pons_chain_rpc",
        "preview_only": preview_only,
        "calls": calls,
    }


def pons_eth_usd_pool_price():
    def read_pool(fee):
        data = (
            "0x1698ee82"
            + PONS_WETH[2:].rjust(64, "0")
            + PONS_USDG[2:].rjust(64, "0")
            + f"{fee:064x}"
        )
        try:
            pool_result = rpc_call(
                "eth_call",
                [{"to": PONS_V3_FACTORY, "data": data}, "latest"],
            )
            pool = "0x" + pool_result[-40:]
            if int(pool, 16) == 0:
                return None, f"fee {fee}: pool not deployed"
            pool_calls = [
                ("eth_call", [{"to": pool, "data": "0x0dfe1681"}, "latest"]),
                ("eth_call", [{"to": pool, "data": "0xd21220a7"}, "latest"]),
                ("eth_call", [{"to": pool, "data": "0x3850c7bd"}, "latest"]),
                ("eth_call", [{"to": pool, "data": "0x1a686502"}, "latest"]),
                ("eth_call", [{"to": PONS_WETH, "data": "0x313ce567"}, "latest"]),
                ("eth_call", [{"to": PONS_USDG, "data": "0x313ce567"}, "latest"]),
            ]
            try:
                token0_result, token1_result, slot0, liquidity_result, weth_decimals, usdg_decimals = rpc_batch(pool_calls)
            except (RuntimeError, ValueError, TypeError):
                (
                    token0_result,
                    token1_result,
                    slot0,
                    liquidity_result,
                    weth_decimals,
                    usdg_decimals,
                ) = [
                    rpc_call(method, params)
                    for method, params in pool_calls
                ]
            token0 = "0x" + token0_result[-40:]
            token1 = "0x" + token1_result[-40:]
            token0 = token0.lower()
            token1 = token1.lower()
            if {token0, token1} != {PONS_WETH, PONS_USDG}:
                return None, f"fee {fee}: pool token addresses do not match WETH/USDG"
            sqrt_price = int(slot0[2:66], 16)
            liquidity = int(liquidity_result, 16)
            weth_decimals = int(weth_decimals, 16)
            usdg_decimals = int(usdg_decimals, 16)
            decimals0 = weth_decimals if token0 == PONS_WETH else usdg_decimals
            decimals1 = usdg_decimals if token1 == PONS_USDG else weth_decimals
            if sqrt_price <= 0 or liquidity <= 0 or decimals0 > 36 or decimals1 > 36:
                return None, f"fee {fee}: pool has invalid price, liquidity, or decimals"
            raw_ratio = Decimal(sqrt_price) ** 2 / Decimal(2**192)
            if token0 == PONS_WETH:
                price = raw_ratio * Decimal(10) ** (decimals0 - decimals1)
            else:
                price = Decimal(1) / raw_ratio * Decimal(10) ** (decimals1 - decimals0)
            if not price.is_finite() or price <= 0 or price > 1_000_000:
                return None, f"fee {fee}: pool returned an implausible ETH/USDG price"
            return (liquidity, float(price), fee), None
        except (RuntimeError, ValueError, TypeError, IndexError) as exc:
            return None, f"fee {fee}: {exc}"

    errors = []
    for fee in PONS_V3_FEES:
        result, error = read_pool(fee)
        if result is not None:
            return result[1], f"pons_v3_weth_usdg_fee_{fee}"
        if error:
            errors.append(error)
    raise RuntimeError(
        "No liquid Robinhood Chain WETH/USDG pool is available (" + "; ".join(errors) + ")"
    )


def _eth_usd_price_locked():
    now = time.time()
    if ETH_USD_CACHE["price"] is not None and now - ETH_USD_CACHE["updated_at"] < 15:
        return ETH_USD_CACHE["price"]
    errors = []
    try:
        price, source = pons_eth_usd_pool_price()
        ETH_USD_CACHE.update({"price": price, "updated_at": now, "source": source})
        return price
    except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
        errors.append(f"Robinhood Chain pool: {exc}")

    providers = (
        (
            "coinbase_eth_usd",
            "https://api.exchange.coinbase.com/products/ETH-USD/ticker",
            lambda payload: float(payload["price"]),
        ),
        (
            "kraken_eth_usd",
            "https://api.kraken.com/0/public/Ticker",
            lambda payload: float(next(iter(payload["result"].values()))["c"][0]),
        ),
    )
    for source, url, decode in providers:
        try:
            response = requests.get(
                url,
                headers={"user-agent": "Noryx/1.0", "accept": "application/json"},
                timeout=8,
            )
            response.raise_for_status()
            price = decode(response.json())
            if not price > 0:
                raise ValueError("provider returned no positive price")
            ETH_USD_CACHE.update({"price": price, "updated_at": now, "source": source})
            return price
        except (requests.RequestException, ValueError, KeyError, TypeError, StopIteration) as exc:
            errors.append(f"{source}: {exc}")
    raise RuntimeError("Unable to read ETH/USD from Robinhood Chain or exchange feeds: " + "; ".join(errors))


def eth_usd_price():
    with ETH_USD_CACHE_LOCK:
        return _eth_usd_price_locked()


def eth_usd_price_source():
    return ETH_USD_CACHE["source"]


def pons_status_snapshot():
    head = int(rpc_call("eth_blockNumber", []), 16)
    status = {
        "ok": True,
        "chain_id": CHAIN_ID,
        "head": head,
        "timestamp": int(time.time()),
        "source": "pons_chain_rpc",
        "eth_usd": None,
        "eth_usd_source": None,
    }
    try:
        status["eth_usd"] = eth_usd_price()
        status["eth_usd_source"] = eth_usd_price_source()
    except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
        status["eth_usd_error"] = str(exc)
    return status


def pons_wallet_balances(query):
    owner = query.get("owner", "").lower()
    token = query.get("tok", "").lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", owner):
        raise ValueError("A valid wallet address is required.")
    if not re.fullmatch(r"0x[0-9a-f]{40}", token):
        raise ValueError("A valid Pons token address is required.")
    record = pons_factory_record(token)
    if record is None:
        raise LookupError("This token is not registered by the Pons factory.")
    metadata = pons_token_metadata(token)
    decimals = metadata.get("decimals")
    if not isinstance(decimals, int) or not 0 <= decimals <= 36:
        raise RuntimeError("Pons token decimals could not be read from chain.")
    eth_raw, token_raw, block = (
        int(value, 16)
        for value in (
            rpc_call("eth_getBalance", [owner, "latest"]),
            rpc_call("eth_call", [{"to": token, "data": "0x70a08231" + owner[2:].rjust(64, "0")}, "latest"]),
            rpc_call("eth_blockNumber", []),
        )
    )
    return {
        "owner": owner,
        "token_address": token,
        "eth_raw": str(eth_raw),
        "eth": decimal_units(eth_raw, 18),
        "token": {
            "address": token,
            "symbol": metadata.get("symbol", ""),
            "decimals": decimals,
            "raw": str(token_raw),
            "balance": decimal_units(token_raw, decimals),
        },
        "block": block,
        "chain_id": CHAIN_ID,
        "source": "pons_chain_rpc",
    }


def public_openapi_spec():
    def operation(summary, path_params=(), query_params=()):
        params = [
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
            for name in path_params
        ]
        params.extend(
            {
                "name": name,
                "in": "query",
                "required": name in {"owner", "tok"},
                "schema": {"type": "string"},
            }
            for name in query_params
        )
        return {
            "summary": summary,
            "parameters": params,
            "responses": {
                "200": {"description": "Live Robinhood Chain/Pons data"},
                "400": {"description": "Invalid request"},
                "501": {"description": "Requested live data source is not available"},
                "503": {"description": "RPC or upstream provider unavailable"},
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Noryx public data API",
            "version": "1.0.0",
            "description": "Live Robinhood Chain/Pons data. Market history is backed by the local on-chain indexer when its reported coverage is complete.",
        },
        "servers": [{"url": "/"}],
        "paths": {
            "/api/status": {"get": operation("Current Robinhood Chain block and ETH/USD reference")},
            "/api/pons/indexer": {"get": operation("Persistent Pons and v4 pool indexer coverage and health")},
            "/api/health": {"get": operation("RPC-backed service health")},
            "/api/feed": {"get": operation("Recent active ETH-paired Pons launch curves", query_params=("column", "offset", "limit"))},
            "/api/search": {"get": operation("Search recent Pons launches", query_params=("q", "offset", "limit"))},
            "/api/token/{address}": {"get": operation("Pons token metadata and live curve quote", path_params=("address",))},
            "/api/token/{address}/market": {"get": operation("Pons token price, supply, and market cap", path_params=("address",))},
            "/api/token/{address}/candles": {"get": operation("Trade-based OHLC candles from indexed Pons curves and Robinhood v4 pools when coverage is complete", path_params=("address",), query_params=("tf", "before"))},
            "/api/token/{address}/trades": {"get": operation("Recent indexed Pons curve and Robinhood v4 pool trades", path_params=("address",), query_params=("limit",))},
            "/api/token/{address}/flow": {"get": operation("Pons curve and indexed pool trade volume and buy/sell flow windows", path_params=("address",))},
            "/api/trending": {"get": operation("Rank Pons tokens by indexed curve and Robinhood v4 pool trades when coverage is complete", query_params=("window", "sort", "limit"))},
            "/api/feed/stream": {"get": operation("Server-sent events for new Pons launches and block updates")},
            "/api/trade/quote": {"get": operation("Read-only Pons ETH curve quote", query_params=("tok", "owner", "side", "wei", "pct", "slippage"))},
            "/api/trade/balances": {"get": operation("Live ETH and Pons token balance", query_params=("owner", "tok"))},
        },
    }


def pons_market_data(address, record, metadata):
    address = address.lower()
    cached = PONS_MARKET_CACHE.get(address)
    now = time.time()
    if cached is not None and now - cached[0] < 3:
        return cached[1].copy()

    decimals = metadata.get("decimals")
    market = {
        "supply": None,
        "supply_raw": None,
        "price_eth": None,
        "price_usd": None,
        "mcap_usd": None,
        "vol1h_usd": None,
        "txns": None,
        "source": "pons_chain_rpc",
        "market_data_pending": ["trade_history"],
    }
    if not isinstance(decimals, int) or not 0 <= decimals <= 36:
        market["market_error"] = "Token decimals could not be read from chain."
        return market

    try:
        total_supply = int(
            rpc_call("eth_call", [{"to": address, "data": "0x18160ddd"}, "latest"]),
            16,
        )
        market["supply_raw"] = str(total_supply)
        market["supply"] = decimal_units(total_supply, decimals)
    except (RuntimeError, ValueError, TypeError) as exc:
        market["supply_error"] = str(exc)

    if int(record["pair_token"], 16) != 0:
        market["market_error"] = "Live Pons market data currently supports ETH-paired launch curves and pools only."
        market["market_data_pending"] = ["supported_quote_market"]
        PONS_MARKET_CACHE[address] = (time.time(), market.copy())
        return market
    if record["phase"] != 0:
        market.update(
            pons_indexed_market_snapshot(
                address,
                decimals,
                market.get("supply_raw"),
            )
        )
        if market.get("price_eth") is None:
            market["market_data_pending"] = ["indexed_trade"]
            market["market_error"] = (
                "No indexed Robinhood v4 pool trade is available yet; the market price is not estimated."
            )
        else:
            market["market_data_pending"] = (
                [] if market.get("vol1h_usd") is not None else ["recent_activity"]
            )
        PONS_MARKET_CACHE[address] = (time.time(), market.copy())
        return market
    try:
        quote = pons_curve_quote(
            {
                "tok": address,
                "owner": "0x0000000000000000000000000000000000000001",
                "side": "buy",
                "wei": "1000000000000000",
                "slippage": "0",
            }
        )
        token_out = int(quote["out_raw"])
        if token_out <= 0:
            raise ValueError("Pons curve returned zero token output.")
        price_eth = Decimal("0.001") / (Decimal(token_out) / Decimal(10**decimals))
        market["price_eth"] = str(price_eth)
        market["price_method"] = "pons_curve_buy_quote"
        try:
            eth_usd = Decimal(str(eth_usd_price()))
            price_usd = price_eth * eth_usd
            market["price_usd"] = str(price_usd)
            if market["supply_raw"] is not None:
                market["mcap_usd"] = str(
                    price_usd * Decimal(market["supply_raw"]) / Decimal(10**decimals)
                )
            market["eth_usd"] = str(eth_usd)
            market["eth_usd_source"] = eth_usd_price_source()
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
            market["price_usd_error"] = str(exc)
    except (PonsQuoteError, RuntimeError, ValueError, TypeError) as exc:
        market["market_error"] = str(exc)

    indexed = pons_indexed_market_snapshot(address, decimals, market.get("supply_raw"))
    for key in ("vol1h_usd", "txns", "last_trade", "indexer"):
        if key in indexed:
            market[key] = indexed[key]
    if market.get("vol1h_usd") is not None or market.get("txns") is not None:
        market["market_data_pending"] = []
        market["source"] = "pons_chain_rpc+pons_market_indexer"

    PONS_MARKET_CACHE[address] = (time.time(), market.copy())
    return market


def pons_indexed_market_snapshot(address, decimals, supply_raw=None):
    now = int(time.time())
    with sqlite3.connect(DATABASE) as connection:
        latest = connection.execute(
            """SELECT tx_hash, log_index, venue, side, quote_raw, token_raw,
                actor, recipient, block_number, timestamp
            FROM pons_market_trades
            WHERE token = ?
            ORDER BY block_number DESC, log_index DESC
            LIMIT 1""",
            (address.lower(),),
        ).fetchone()
        recent = connection.execute(
            """SELECT quote_raw FROM pons_market_trades
            WHERE token = ? AND timestamp >= ? AND timestamp <= ?""",
            (address.lower(), now - 3600, now),
        ).fetchall()
    state = pons_index_state()
    updated_at = int(state.get("updated_at", "0"))
    running = PONS_INDEXER_THREAD is not None and PONS_INDEXER_THREAD.is_alive()
    summary = {
        "indexer": {
            "running": running,
            "healthy": running and updated_at > 0 and now - updated_at <= 30 and not state.get("last_error"),
            "indexed_head": int(state.get("live_cursor", "0")),
            "updated_at": updated_at,
        }
    }
    if latest is not None:
        tx_hash, log_index, venue, side, quote_raw, token_raw, actor, recipient, block, timestamp = latest
        token_amount = Decimal(token_raw) / Decimal(10**decimals)
        quote_amount = Decimal(quote_raw) / Decimal(10**18)
        if token_amount > 0 and quote_amount > 0:
            price_eth = quote_amount / token_amount
            summary["price_eth"] = str(price_eth)
            summary["price_method"] = "last_indexed_pons_trade"
            summary["source"] = "pons_market_indexer"
            summary["last_trade"] = {
                "tx": tx_hash,
                "idx": log_index,
                "venue": venue,
                "side": side,
                "timestamp": timestamp,
                "age_seconds": max(0, now - timestamp),
                "block": block,
                "actor": actor,
                "recipient": recipient,
            }
            try:
                eth_usd = Decimal(str(eth_usd_price()))
                price_usd = price_eth * eth_usd
                summary["price_usd"] = str(price_usd)
                summary["eth_usd"] = str(eth_usd)
                if supply_raw is not None:
                    summary["mcap_usd"] = str(
                        price_usd
                        * Decimal(supply_raw)
                        / Decimal(10**decimals)
                    )
                    summary["mcap_method"] = "last_indexed_pons_trade_x_total_supply"
            except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
                summary["price_usd_error"] = str(exc)
    if recent:
        volume_eth = sum(Decimal(row[0]) for row in recent) / Decimal(10**18)
        summary["txns"] = len(recent)
        try:
            summary["vol1h_usd"] = float(volume_eth * Decimal(str(eth_usd_price())))
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
            summary["volume_usd_error"] = str(exc)
    return summary


def enrich_pons_progress(row, record=None):
    if row.get("progress") is not None or row["phase"] != 0:
        return row
    record = record or pons_factory_record(row["token"])
    threshold = int(row.get("graduation_threshold") or 0)
    if record is None or threshold <= 0:
        return row
    try:
        curve_balance = int(rpc_call("eth_getBalance", [record["curve"], "latest"]), 16)
        row["progress"] = round(min(100.0, curve_balance * 100.0 / threshold), 2)
        row["progress_method"] = "curve_eth_balance/graduation_threshold"
    except (RuntimeError, ValueError, TypeError) as exc:
        row["progress_error"] = str(exc)
    return row


def enrich_pons_row(row):
    record = pons_factory_record(row["token"])
    if record is None:
        raise ValueError(f"Pons factory has no current launch record for {row['token']}")
    enrich_pons_progress(row, record)
    meta_extra = pons_token_metadata_extra(row["token"])
    for k in ("image", "x_url", "x_handle", "tg_url", "site", "description"):
        if meta_extra.get(k) and not row.get(k):
            row[k] = meta_extra[k]
    t_metrics = pons_token_metrics(row["token"], sync_fallback=False)
    if t_metrics:
        for k, v in t_metrics.items():
            if k != "updated_at":
                row[k] = v
    else:
        row.setdefault("holders", None)
        row.setdefault("buyers", None)
        row.setdefault("top10_pct", None)
        row.setdefault("creator_pct", None)
        row.setdefault("dev_holds_pct", None)
        row.setdefault("snipe_pct", None)
        row.setdefault("bundle_pct", None)
        row.setdefault("smart", 0)
        row.setdefault("tax_bps", 0)
        row.setdefault("score", None)
        row.setdefault("score_band", None)
        row.setdefault("score_confidence", "partial")
        row.setdefault("score_factors", [])
        row.setdefault("score_unmeasured", [])
    metadata = pons_token_metadata(row["token"])
    market = pons_market_data(row["token"], record, metadata)
    trade_metrics = {}
    try:
        flow = pons_trade_flow(row["token"], record)
        for window, values in flow["w"].items():
            trade_metrics[f"vol_{window}_usd"] = values["vol_usd"]
            trade_metrics[f"vol{window}_usd"] = values["vol_usd"]
            trade_metrics[f"chg_{window}_pct"] = flow["chg"][window]
            trade_metrics[f"buys_{window}"] = values["buys"]
            trade_metrics[f"sells_{window}"] = values["sells"]
            trade_metrics[f"txns_{window}"] = values["n"]
        trade_metrics.update(
            {
                "txns": flow["w"]["1h"]["n"],
                "buys": flow["w"]["5m"]["buys"],
                "sells": flow["w"]["5m"]["sells"],
                "trade_history_available": True,
                "trade_history_partial": flow["partial"],
                "trade_history_source": flow["source"],
            }
        )
    except (RuntimeError, ValueError, TypeError, PonsQuoteError) as exc:
        trade_metrics.update(
            {
                "trade_history_available": False,
                "trade_history_error": str(exc),
                "trade_history_source": "pons_chain_rpc_trade_events",
            }
        )
    return {**row, **market, **trade_metrics}


def custody_report():
    checked_at = int(time.time())
    key_name = re.compile(
        r"(?:^|_)(?:PRIVATE_?KEY|SIGNING_?KEY|WALLET_(?:PRIVATE_?)?KEY|"
        r"WALLET_SECRET|MNEMONIC|SEED(?:_PHRASE)?)(?:_|$)",
        re.IGNORECASE,
    )
    private_key_value = re.compile(r"(?:0x)?[0-9a-f]{64}", re.IGNORECASE)
    seed_phrase_value = re.compile(r"(?:[a-z]+\s+){11,23}[a-z]+", re.IGNORECASE)
    flagged = sorted(
        name
        for name, value in os.environ.items()
        if key_name.search(name)
        or private_key_value.fullmatch(value.strip())
        or seed_phrase_value.fullmatch(value.strip())
    )
    try:
        block = int(rpc_call("eth_blockNumber", []), 16)
        head = {"block": block, "age_s": 0}
    except (RuntimeError, ValueError, TypeError):
        head = None

    contracts = [
        {
            "key": key,
            "chain": chain,
            "address": address,
            "pinned": pinned,
            "live": None,
            "status": "unavailable",
        }
        for key, chain, address, pinned in TRUST_CONTRACTS
    ]
    return {
        "state": "alert" if flagged else "partial",
        "checked_at": checked_at,
        "checked_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(checked_at)),
        "pinned_at": TRUST_PINNED_AT,
        "head": head,
        "keys": {
            "ok": not flagged,
            "variables_checked": len(os.environ),
            "flagged": flagged,
        },
        "contracts": contracts,
        "counts": {"match": 0, "contracts": len(contracts)},
        "source": "Sentro custody baseline",
    }


def pons_token_snapshot(address):
    address = address.lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", address):
        return None
    record = pons_factory_record(address)
    if record is None:
        return None
    metadata = pons_token_metadata(address)
    meta_extra = pons_token_metadata_extra(address, sync_fallback=True)
    pair_token = record["pair_token"]
    phase = record["phase"]
    market = pons_market_data(address, record, metadata)
    token = {
        "address": address,
        "name": metadata.get("name", ""),
        "symbol": metadata.get("symbol", ""),
        "decimals": metadata.get("decimals"),
        "metadata_available": metadata["metadata_available"],
        "image": meta_extra.get("image"),
        "x_url": meta_extra.get("x_url"),
        "x_handle": meta_extra.get("x_handle"),
        "tg_url": meta_extra.get("tg_url"),
        "site": meta_extra.get("site"),
        "description": meta_extra.get("description"),
        "chain_id": CHAIN_ID,
        "curve": record["curve"],
        "phase": phase,
        "pair_token": pair_token,
        "quote": "ETH" if int(pair_token, 16) == 0 else pair_token,
        "launchpad": "pons",
        "venue": "curve" if phase == 0 else "pool",
        "stage": "launched" if phase == 0 else "migrated",
        **market,
        "trades": [],
        "flow": [],
        "source": "pons_chain_rpc",
        "read_only": True,
    }
    t_metrics = pons_token_metrics(address, sync_fallback=True)
    if t_metrics:
        token["holders"] = t_metrics["holders"]
        token["holders_count"] = t_metrics["holders"]
        token["buyers"] = t_metrics["buyers"]
        token["top10_pct"] = t_metrics["top10_pct"]
        token["creator_pct"] = t_metrics["creator_pct"]
        token["dev_holds_pct"] = t_metrics["dev_holds_pct"]
        token["snipe_pct"] = t_metrics["snipe_pct"]
        token["bundle_pct"] = t_metrics["bundle_pct"]
        token["smart"] = t_metrics["smart"]
        token["tax_bps"] = t_metrics["tax_bps"]
        token["score"] = t_metrics["score"]
        token["score_band"] = t_metrics["score_band"]
        token["score_confidence"] = t_metrics["score_confidence"]
        token["score_factors"] = t_metrics["score_factors"]
        token["score_unmeasured"] = t_metrics["score_unmeasured"]
    else:
        token["holders"] = None
        token["holders_count"] = None
        token["buyers"] = None
        token["top10_pct"] = None
        token["creator_pct"] = None
        token["dev_holds_pct"] = None
        token["snipe_pct"] = None
        token["bundle_pct"] = None
        token["smart"] = 0
        token["tax_bps"] = 0
        token["score"] = None
        token["score_band"] = None
        token["score_confidence"] = "partial"
        token["score_factors"] = []
        token["score_unmeasured"] = []
    if metadata.get("metadata_error"):
        token["metadata_error"] = metadata["metadata_error"]
    if market.get("market_error"):
        token["price_error"] = {
            "code": "market_data_unavailable",
            "detail": market["market_error"],
        }
    return {
        **token,
        "token": token,
        "source": "pons_chain_rpc",
        "read_only": True,
    }


def feed_token(address):
    return pons_token_snapshot(address)


def token_snapshot(address):
    return pons_token_snapshot(address)


def gemini_answer(question, token=None, messages=None):
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY on the server.")
    prompt = (
        "You are Noryx AI, a concise crypto market research assistant for Robinhood Chain "
        "(chain ID 4663). Use only the supplied context, clearly label uncertainty, and never "
        "claim to have executed a trade. Answer in plain text.\n\n"
        f"Question: {question}\n"
    )
    if token:
        prompt += f"\nToken context (untrusted market data): {json.dumps(token, ensure_ascii=False)[:12000]}\n"
    if messages:
        prompt += f"\nConversation context: {json.dumps(messages, ensure_ascii=False)[:12000]}\n"
    models = list(dict.fromkeys([GEMINI_MODEL, "gemini-3.5-flash", "gemini-3.5-flash-lite"]))
    last_response = None
    for model in models:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": GEMINI_API_KEY},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
            },
            headers={"user-agent": "Noryx/1.0", "accept": "application/json"},
            timeout=30,
        )
        if response.ok:
            body = response.json()
            break
        last_response = response
        if response.status_code not in {404, 429, 500, 503}:
            response.raise_for_status()
    else:
        last_response.raise_for_status()
    try:
        return body["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini returned no answer") from exc


class NoryxHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, events):
        body = b"".join(
            f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()
            for event, payload in events
        )
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "keep-alive")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream_pons_feed(self):
        try:
            status = pons_status_snapshot()
            cursor = status["head"]
        except (RuntimeError, ValueError, TypeError) as exc:
            self.send_json(503, {"error": "pons_rpc_unavailable", "detail": str(exc)})
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache, no-store")
        self.send_header("connection", "keep-alive")
        self.send_header("access-control-allow-origin", "*")
        self.end_headers()
        try:
            self.wfile.write(
                f"event: hello\ndata: {json.dumps({**status, 't': status['timestamp']})}\n\n".encode()
            )
            self.wfile.flush()
            for _ in range(20):
                time.sleep(3)
                status = pons_status_snapshot()
                head = status["head"]
                if head > cursor:
                    logs = pons_launch_logs(cursor + 1, head)
                    ordered = sorted(logs, key=lambda event: int(event["blockNumber"], 16))
                    with ThreadPoolExecutor(max_workers=12) as executor:
                        rows = list(executor.map(pons_launch_row, ordered))
                    rows = [row for row in rows if pons_curve_is_tradable(row)]
                    if rows:
                        rows = [enrich_pons_row(row) for row in rows]
                        payload = json.dumps({"rows": rows, "source": "pons_chain_rpc"}, ensure_ascii=False)
                        self.wfile.write(f"event: launch\ndata: {payload}\n\n".encode())
                    cursor = head
                self.wfile.write(
                    f"event: tick\ndata: {json.dumps({**status, 't': status['timestamp']})}\n\n".encode()
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def stream_token(self, address):
        address = address.lower()
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            self.send_json(400, {"error": "invalid_address", "address": address})
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-cache, no-store")
        self.send_header("connection", "keep-alive")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("x-accel-buffering", "no")
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

        try:
            initial = feed_token(address)
            if initial is None:
                self.wfile.write(b"event: error\ndata: {\"error\": \"not_a_pons_token\"}\n\n")
                self.wfile.flush()
                return

            db = db_connect()
            try:
                trade_rows = db.execute(
                    """SELECT tx_hash, log_index, side, quote_raw, token_raw, actor, block_number, timestamp
                       FROM pons_market_trades
                       WHERE token=?
                       ORDER BY block_number DESC, log_index DESC
                       LIMIT 50""",
                    (address,)
                ).fetchall()
            finally:
                db.close()
            recent = []
            for r in trade_rows:
                tx_h, l_idx, side, q_raw, tok_raw, actor, blk, ts = r
                recent.append({
                    "tx": tx_h,
                    "idx": l_idx,
                    "side": side,
                    "eth": float(q_raw) / 1e18 if q_raw else 0.0,
                    "actor": actor,
                    "block": blk,
                    "ts": ts,
                })
            initial["trades"] = recent

            previous_trades = {
                f"{trade['tx']}:{trade['idx']}" for trade in initial.get("trades", [])
            }
            self.wfile.write(
                f"event: tok_hello\ndata: {json.dumps(initial, ensure_ascii=False)}\n\n".encode()
            )
            self.wfile.flush()

            last_block = max([t["block"] for t in initial["trades"]] + [0])
            for _attempt in range(60):
                time.sleep(3)
                db = db_connect()
                try:
                    new_rows = db.execute(
                        """SELECT tx_hash, log_index, side, quote_raw, token_raw, actor, block_number, timestamp
                           FROM pons_market_trades
                           WHERE token=? AND block_number >= ?
                           ORDER BY block_number ASC, log_index ASC""",
                        (address, last_block)
                    ).fetchall()
                finally:
                    db.close()
                for r in new_rows:
                    tx_h, l_idx, side, q_raw, tok_raw, actor, blk, ts = r
                    key = f"{tx_h}:{l_idx}"
                    if key in previous_trades:
                        continue
                    previous_trades.add(key)
                    last_block = max(last_block, blk)
                    trade_obj = {
                        "tx": tx_h,
                        "idx": l_idx,
                        "side": side,
                        "eth": float(q_raw) / 1e18 if q_raw else 0.0,
                        "actor": actor,
                        "block": blk,
                        "ts": ts,
                    }
                    self.wfile.write(
                        f"event: tok_trade\ndata: {json.dumps(trade_obj, ensure_ascii=False)}\n\n".encode()
                    )
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("access-control-allow-headers", "content-type,authorization")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}

        if path == "/v1/openapi.json":
            self.send_json(200, public_openapi_spec())
            return
        if path == "/api/health":
            try:
                status = pons_status_snapshot()
                self.send_json(200, {"ok": True, "service": "noryx", **status})
            except (RuntimeError, ValueError, TypeError) as exc:
                self.send_json(503, {"ok": False, "service": "noryx", "chain_id": CHAIN_ID, "error": str(exc)})
            return
        if path == "/api/status":
            try:
                self.send_json(
                    200,
                    {
                        **pons_status_snapshot(),
                        "market_indexer": pons_market_index_status(),
                    },
                )
            except (RuntimeError, ValueError, TypeError) as exc:
                self.send_json(503, {"ok": False, "chain_id": CHAIN_ID, "source": "pons_chain_rpc", "error": str(exc)})
            return
        if path == "/api/pons/indexer":
            self.send_json(200, pons_market_index_status())
            return
        if path == "/api/config":
            self.send_json(
                200,
                {
                    "chain_id": CHAIN_ID,
                    "rpc_url": RPC_URLS[0],
                    "rpc_fallback": RPC_URLS[1] if len(RPC_URLS) > 1 else None,
                    "market_feed_source": "pons_chain_rpc",
                    "market_feed_window_blocks": PONS_FEED_WINDOW_BLOCKS,
                    "market_data_sources": [
                        "pons_v3_weth_usdg_pool",
                        "coinbase_eth_usd",
                        "kraken_eth_usd",
                        "pons_market_indexer",
                    ],
                    "privy_app_id": PRIVY_APP_ID,
                    "privy_chain_id": CHAIN_ID,
                    "ai_provider": "gemini",
                    "ai_model": GEMINI_MODEL,
                    "ai_configured": bool(GEMINI_API_KEY),
                    "read_only": True,
                },
            )
            return
        if path == "/api/state":
            try:
                self.send_json(200, {**pons_status_snapshot(), "read_only": True})
            except (RuntimeError, ValueError, TypeError) as exc:
                self.send_json(503, {"ok": False, "chain_id": CHAIN_ID, "error": str(exc)})
            return
        if path == "/api/trust/custody":
            self.send_json(200, custody_report())
            return
        if path == "/api/stats":
            try:
                status = pons_status_snapshot()
                start = max(0, status["head"] - max(1, PONS_FEED_WINDOW_BLOCKS))
                logs = pons_launch_logs(start, status["head"])
                token_addresses = list(
                    dict.fromkeys(
                        "0x" + log["topics"][1][-40:]
                        for log in logs
                        if len(log.get("topics", [])) > 1
                    )
                )[:200]
                with ThreadPoolExecutor(max_workers=12) as executor:
                    records = list(executor.map(pons_factory_record, token_addresses))
                active_curves = sum(
                    1
                    for record in records
                    if record is not None
                    and record["phase"] == 0
                    and int(record["pair_token"], 16) == 0
                )
                self.send_json(
                    200,
                    {
                        **status,
                        "window_start": start,
                        "launch_events_in_window": len(logs),
                        "active_eth_curves_in_sample": active_curves,
                        "sample_size": len(token_addresses),
                        "scan_truncated": len(logs) > 200,
                        "volume_usd": None,
                        "volume_status": "Trade volume is available from verified Pons events through /api/trending.",
                    },
                )
            except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_stats_unavailable", "detail": str(exc)})
            return
        if path == "/api/feed":
            try:
                self.send_json(200, pons_feed(query))
            except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_feed_unavailable", "detail": str(exc)})
            return
        if path == "/api/search":
            search_term = query.get("q", "").strip().lower()
            if len(search_term) < 2:
                self.send_json(200, {"rows": [], "source": "pons_chain_rpc", "chain_id": CHAIN_ID})
                return
            try:
                self.send_json(200, pons_feed(query, search_term))
            except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_search_unavailable", "detail": str(exc)})
            return
        if path in {"/api/trending", "/api/tops"}:
            try:
                payload = pons_trending(query)
                if path == "/api/tops":
                    payload = {**payload, "items": payload["rows"]}
                self.send_json(200, payload)
            except PonsQuoteError as exc:
                self.send_json(exc.status, {"error": exc.code, "detail": str(exc), "source": "pons_chain_rpc"})
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_trending_request", "detail": str(exc)})
            except (RuntimeError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_trending_unavailable", "detail": str(exc)})
            return
        if path == "/api/me":
            self.send_json(
                501,
                {
                    "error": "server_auth_not_configured",
                    "detail": "Privy email login is client-side; server-verified API account endpoints are not enabled.",
                },
            )
            return
        if path == "/api/feed/lists":
            try:
                columns = {}
                items = []
                seen = set()
                for column in ("new", "bonding", "migrated"):
                    payload = pons_feed({"column": column, "limit": "200", "offset": "0"})
                    column_rows = payload.get("rows", [])
                    columns[column] = len(column_rows)
                    for row in column_rows:
                        token = str(row.get("token", "")).lower()
                        if not token or token in seen:
                            continue
                        seen.add(token)
                        items.append({
                            "token": row["token"],
                            "name": row.get("name") or row["token"][:8],
                            "symbol": row.get("symbol") or "TKN",
                        })
                items.sort(key=lambda item: item["token"])
                self.send_json(
                    200,
                    {
                        "items": items,
                        "rows": items,
                        "total": len(items),
                        "columns": columns,
                        "source": "pons_chain_rpc",
                    },
                )
            except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_feed_lists_unavailable", "detail": str(exc), "items": [], "rows": [], "total": 0})
            return
        if path in {
            "/api/feed",
            "/api/tops",
            "/api/trending",
            "/api/migrations",
            "/api/pairs",
            "/api/stocks",
        }:
            try:
                payload = indexer_json(path, query)
                self.send_json(200, payload)
            except RuntimeError as exc:
                self.send_json(501, {"error": "data_source_not_configured", "detail": str(exc), "items": []})
            except (requests.RequestException, ValueError) as exc:
                self.send_json(503, {"error": "indexer_unavailable", "detail": str(exc), "items": []})
            return
        if path == "/api/feed/stream":
            if query.get("token"):
                self.stream_token(query["token"])
            else:
                self.stream_pons_feed()
            return
        if path.startswith("/api/token/") and path.endswith("/stream"):
            self.stream_token(path.split("/")[3])
            return
        if path.startswith("/api/token/") and path.endswith("/flow"):
            address = path.split("/")[3]
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                self.send_json(400, {"error": "invalid_address", "address": address})
                return
            try:
                self.send_json(200, pons_trade_flow(address.lower()))
            except PonsQuoteError as exc:
                self.send_json(exc.status, {"error": exc.code, "detail": str(exc), "source": "pons_chain_rpc"})
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_flow_request", "detail": str(exc)})
            except (RuntimeError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_flow_unavailable", "detail": str(exc)})
            return
        if path.startswith("/api/token/") and (
            path.endswith("/candles") or path.endswith("/trades")
        ):
            address = path.split("/")[3]
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                self.send_json(400, {"error": "invalid_address", "address": address})
                return
            try:
                payload = (
                    pons_token_candles(address.lower(), query)
                    if path.endswith("/candles")
                    else pons_token_trades(address.lower(), query)
                )
                self.send_json(200, payload)
            except PonsQuoteError as exc:
                self.send_json(exc.status, {"error": exc.code, "detail": str(exc), "source": "pons_chain_rpc"})
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_history_request", "detail": str(exc)})
            except (RuntimeError, TypeError, requests.RequestException) as exc:
                self.send_json(503, {"error": "pons_rpc_unavailable", "detail": str(exc), "items": []})
            return
        if path.startswith("/api/token/") and path.endswith("/holders"):
            address = path.split("/")[3]
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                self.send_json(400, {"error": "invalid_address", "address": address})
                return
            creator_param = query.get("creator", [None])[0]
            try:
                payload = pons_token_holders(address.lower(), creator=creator_param)
                self.send_json(200, payload)
            except Exception as exc:
                self.send_json(503, {"error": "holders_unavailable", "detail": str(exc), "holders": [], "count": 0})
            return
        if path.startswith("/api/token/") and path.endswith("/traders"):
            address = path.split("/")[3]
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                self.send_json(400, {"error": "invalid_address", "address": address})
                return
            try:
                self.send_json(200, pons_token_traders(address.lower()))
            except Exception as exc:
                self.send_json(503, {"error": "traders_unavailable", "detail": str(exc), "traders": []})
            return
        if path.startswith("/api/token/") or path.startswith("/api/check/"):
            parts = path.split("/")
            address = parts[3] if len(parts) > 3 else ""
            if path.startswith("/api/token/") and len(parts) > 4 and parts[4] not in {"market", "preview", "boot", "holders", "traders", "check", "candles", "trades", "flow", "stream"}:
                self.send_json(
                    501,
                    {
                        "error": "pons_endpoint_not_available",
                        "detail": "This token endpoint is not yet backed by verified Pons on-chain data.",
                        "source": "pons_chain_rpc",
                    },
                )
                return
            if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
                self.send_json(400, {"error": "invalid_address", "address": address})
                return
            try:
                token = feed_token(address)
            except (RuntimeError, ValueError, TypeError, PonsQuoteError) as exc:
                self.send_json(503, {"error": "pons_rpc_unavailable", "detail": str(exc)})
                return
            if token:
                if path.endswith("/boot"):
                    self.send_json(
                        200,
                        {
                            "address": address,
                            "token": token["token"],
                            "check": token,
                            "market": token,
                            "pending": [],
                            "source": "pons_chain_rpc",
                            "read_only": True,
                        },
                    )
                else:
                    self.send_json(200, {**token, "address": address})
                return
            self.send_json(
                404,
                {
                    "error": "not_a_pons_token",
                    "address": address,
                    "items": [],
                    "source": "pons_chain_rpc",
                    "read_only": True,
                },
            )
            return
        if path.startswith("/api/portfolio/") or path.startswith("/api/tracker/"):
            self.send_json(
                501,
                {
                    "error": "history_not_available",
                    "detail": "Wallet history is not currently indexed from Robinhood Chain RPC.",
                    "source": "pons_chain_rpc",
                },
            )
            return
        if path == "/api/wallet/tokens":
            self.send_json(
                501,
                {
                    "error": "wallet_tokens_not_available",
                    "detail": "Token discovery for a wallet is not currently indexed from Robinhood Chain RPC.",
                },
            )
            return
        if path.endswith("/stream") and path.startswith("/api/"):
            self.send_json(
                501,
                {
                    "error": "stream_not_available",
                    "detail": "This live stream is not implemented for the requested resource.",
                },
            )
            return
        if path.startswith("/api/wallet/") and path.endswith("/summary"):
            address = path.split("/")[3]
            try:
                self.send_json(200, self.wallet_summary(address))
            except (RuntimeError, ValueError, TypeError) as exc:
                self.send_json(503, {"error": "wallet_rpc_unavailable", "detail": str(exc)})
            return
        if path == "/api/trade/balances":
            try:
                self.send_json(200, pons_wallet_balances(query))
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_balance_request", "detail": str(exc)})
            except LookupError as exc:
                self.send_json(404, {"error": "not_a_pons_token", "detail": str(exc)})
            except (RuntimeError, TypeError) as exc:
                self.send_json(503, {"error": "pons_balance_unavailable", "detail": str(exc)})
            return
        if path == "/api/trade/quote":
            try:
                self.send_json(200, pons_curve_quote(query))
            except PonsQuoteError as exc:
                self.send_json(exc.status, {"error": exc.code, "detail": str(exc)})
            except (RuntimeError, ValueError, TypeError, requests.RequestException) as exc:
                self.send_json(
                    503,
                    {"error": "pons_quote_unavailable", "detail": str(exc)},
                )
            return
        if path.startswith("/api/token/"):
            self.send_json(
                501,
                {
                    "error": "pons_endpoint_not_available",
                    "detail": "This token endpoint is not yet backed by verified Pons on-chain data.",
                    "source": "pons_chain_rpc",
                },
            )
            return
        if path == "/api/me/tracked":
            self.send_json(200, {"wallets": self.tracked_wallets("local")})
            return
        if path == "/api/me/prefs":
            self.send_json(200, self.preferences("local"))
            return
        if path == "/api/plans":
            self.send_json(501, {"error": "plans_not_configured", "detail": "Paid API plans are not enabled."})
            return
        if path.startswith("/api/") and (
            "/ai" in path or "/trade/" in path or "/bridge/" in path or "/wallet/convert" in path
        ):
            self.send_json(
                501,
                {
                    "error": "not_configured",
                    "detail": "This read-only backend does not execute trades, AI, or bridge operations.",
                },
            )
            return
        if path.startswith("/api/"):
            if "/bridge/" in path:
                self.send_json(
                    501,
                    {
                        "error": "bridge_not_configured",
                        "detail": "Bridge quotes and execution are not configured for Robinhood Chain.",
                    },
                )
                return
            self.send_json(404, {"error": "not_found", "path": path})
            return
        if path.startswith("/img/"):
            self.serve_ipfs_image(path[5:])
            return
        self.serve_static(path)

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/ai/ask":
            payload = self.read_json()
            question = str(payload.get("q", "")).strip()
            if not question or len(question) > 4000:
                self.send_sse([("error", "Ask a question up to 4000 characters.")])
                return
            try:
                answer = gemini_answer(question, payload.get("tok"), payload.get("messages"))
                self.send_sse([("piece", answer), ("done", {"model": GEMINI_MODEL})])
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                self.send_sse([("error", str(exc))])
            return
        if path == "/api/wallet/convert" or path.startswith("/api/trade/"):
            self.send_json(
                501,
                {
                    "error": "read_only",
                    "detail": "Trade execution is disabled. Sign transactions in a configured frontend wallet.",
                },
            )
            return
        if path.startswith("/api/"):
            self.send_json(
                501,
                {
                    "error": "not_configured",
                    "detail": "Write operations require wallet authentication and explicit production configuration.",
                },
            )
            return
        self.send_json(404, {"error": "not_found"})

    def do_PUT(self):
        path = unquote(urlparse(self.path).path)
        payload = self.read_json()
        if path == "/api/me/prefs":
            with sqlite3.connect(DATABASE) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO preferences(session_id, payload) VALUES (?, ?)",
                    ("local", json.dumps(payload or {})),
                )
            self.send_json(200, payload or {})
            return
        if path == "/api/me/tracked":
            wallets = payload.get("addresses", []) if isinstance(payload, dict) else []
            with sqlite3.connect(DATABASE) as connection:
                connection.execute("DELETE FROM tracked_wallets WHERE session_id = ?", ("local",))
                connection.executemany(
                    "INSERT OR REPLACE INTO tracked_wallets(session_id, address, label) VALUES (?, ?, ?)",
                    [("local", item.get("address", ""), item.get("label", "")) for item in wallets if item.get("address")],
                )
            self.send_json(200, {"wallets": self.tracked_wallets("local")})
            return
        self.do_POST()

    def do_DELETE(self):
        self.do_POST()

    def read_json(self):
        try:
            length = int(self.headers.get("content-length", "0"))
            return json.loads(self.rfile.read(length)) if length else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    def preferences(self, session_id):
        with sqlite3.connect(DATABASE) as connection:
            row = connection.execute(
                "SELECT payload FROM preferences WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return {}

    def tracked_wallets(self, session_id):
        with sqlite3.connect(DATABASE) as connection:
            rows = connection.execute(
                "SELECT address, label FROM tracked_wallets WHERE session_id = ? ORDER BY address",
                (session_id,),
            ).fetchall()
        return [{"address": address, "label": label} for address, label in rows]

    def block_number(self):
        try:
            return int(rpc_call("eth_blockNumber", []), 16)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
            return None

    def wallet_summary(self, address):
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
            raise ValueError("A valid wallet address is required.")
        try:
            balance = int(rpc_call("eth_getBalance", [address, "latest"]), 16)
            block = int(rpc_call("eth_blockNumber", []), 16)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            raise RuntimeError(f"Unable to read wallet balance from Robinhood Chain RPC: {exc}") from exc
        return {
            "address": address,
            "balance_wei": str(balance),
            "balance": decimal_units(balance, 18),
            "valid": True,
            "block": block,
            "chain_id": CHAIN_ID,
            "source": "pons_chain_rpc",
        }

    def serve_static(self, path):
        requested = (WEB_ROOT / path.lstrip("/")).resolve()
        try:
            requested.relative_to(WEB_ROOT.resolve())
        except ValueError:
            self.send_json(400, {"error": "invalid_path"})
            return
        if not requested.is_file() and requested.suffix:
            self.send_json(404, {"error": "not_found"})
            return
        target = requested if requested.is_file() else WEB_ROOT / "index.html"
        try:
            body = target.read_bytes()
        except OSError:
            self.send_json(404, {"error": "not_found"})
            return
        content_type = "text/html; charset=utf-8" if target.suffix == ".html" else "application/octet-stream"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "text/javascript; charset=utf-8"
        elif target.suffix == ".png":
            content_type = "image/png"
        elif target.suffix in {".jpg", ".jpeg"}:
            content_type = "image/jpeg"
        elif target.suffix == ".md":
            content_type = "text/markdown; charset=utf-8"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"
        elif target.suffix == ".webmanifest":
            content_type = "application/manifest+json"
        elif target.suffix == ".woff2":
            content_type = "font/woff2"
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_ipfs_image(self, cid):
        cid = cid.split("?")[0].split("#")[0].strip()
        if cid.startswith(("https://", "http://")):
            self.serve_remote_image(cid)
            return
        if cid.startswith("ipfs://"):
            cid = cid[7:].removeprefix("ipfs/")
        if not cid or "/" in cid or "\\" in cid or not re.fullmatch(r"[A-Za-z0-9_-]{20,120}", cid):
            self.send_json(400, {"error": "invalid_image_path"})
            return
        for gateway in IPFS_GATEWAYS:
            try:
                response = requests.get(
                    gateway + cid,
                    headers={"user-agent": "Noryx/1.0"},
                    timeout=5,
                    stream=True,
                )
                if response.status_code != 200:
                    continue
                content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
                if not content_type.startswith("image/"):
                    continue
                body = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    body.extend(chunk)
                    if len(body) > 5 * 1024 * 1024:
                        break
                if len(body) > 5 * 1024 * 1024:
                    continue
                self.send_response(200)
                self.send_header("content-type", content_type)
                self.send_header("cache-control", "public, max-age=86400")
                self.send_header("content-length", str(len(body)))
                self.send_header("x-content-type-options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            except (requests.RequestException, OSError):
                continue
        self.send_json(404, {"error": "image_unavailable"})

    def serve_remote_image(self, url):
        parsed = urlparse(url)
        if parsed.scheme != "https":
            self.send_json(403, {"error": "https_required"})
            return
        hostname = (parsed.hostname or "").lower()
        if not hostname or hostname not in IMAGE_HOSTS:
            self.send_json(403, {"error": "image_host_not_allowed", "host": hostname})
            return
        try:
            addr_info = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
            for _, _, _, _, sockaddr in addr_info:
                ip = ipaddress.ip_address(sockaddr[0])
                if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                    self.send_json(403, {"error": "private_ip_forbidden"})
                    return
        except Exception:
            self.send_json(404, {"error": "host_resolution_failed"})
            return

        try:
            response = requests.get(
                url,
                headers={"user-agent": "Noryx/1.0"},
                timeout=5,
                stream=True,
            )
            if response.status_code != 200:
                self.send_json(404, {"error": "image_unavailable"})
                return
            content_type = response.headers.get("content-type", "").split(";")[0]
            if not content_type.startswith("image/"):
                self.send_json(415, {"error": "not_an_image"})
                return
            body = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                body.extend(chunk)
                if len(body) > 5 * 1024 * 1024:
                    self.send_json(413, {"error": "image_too_large"})
                    return
            self.send_response(200)
            self.send_header("content-type", content_type)
            self.send_header("cache-control", "public, max-age=86400")
            self.send_header("content-length", str(len(body)))
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(body)
        except (requests.RequestException, OSError):
            self.send_json(404, {"error": "image_unavailable"})


if __name__ == "__main__":
    init_database()
    start_pons_indexer()
    print("Noryx backend berjalan di http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), NoryxHandler).serve_forever()
