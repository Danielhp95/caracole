# Canonical JSON, the stored-JSON hash and kv text

Status: the contract of the Android port's milestones 1–3 (plan:
[2026-11-03-android-port-m1-m3.md](../plans/2026-11-03-android-port-m1-m3.md), §4). Two languages serialize one
record and must get one digest: this file says how, to the byte. The Python reference is `src/caracole/canonical.py`
and the Kotlin one `core.json.Canonical` and `core.json.PyJson` (lane `canonical`), whose vectors are
`tests/conformance/vectors/canonical/`. A change here is a change of the contract: the lane reports it, and the plan
changes with it.

## The strict reading

Canonical hashing reads text exactly as Python's `json.loads(text)` does with its defaults (`strict=True`). Kotlin
has its own small parser for it, never a lenient one.

- Whitespace is only space, `\t`, `\n` and `\r` (U+00A0 and every other space is "not JSON").
- A string may not hold a raw control character below U+0020.
- `01`, `+1`, `.5`, `1.` and a BOM are refused.
- `NaN`, `Infinity` and `-Infinity` are read.
- An integer literal of more than 4300 digits is refused, as Python's int limit refuses it.
- An escaped surrogate pair (`🎸`) is one code point; an escaped lone surrogate (`\ud800`) is read, and is
  then "not canonicalizable" (below).
- When an object repeats a key, the last value wins, as in `json.loads`, and the key appears once.
- A refused text is "not JSON".

## Canonical text `C(v)`

- **Objects.** Members sorted by key in code-point order (not UTF-16 order: a key of U+1F3B8 sorts after one of
  U+FF61), written `{"k":v,…}` with no spaces.
- **Arrays.** `[v,…]`, in order.
- **Strings.**
  - `"` and `\` are written `\"` and `\\`.
  - U+0008, 09, 0A, 0C and 0D are written `\b`, `\t`, `\n`, `\f` and `\r`.
  - Every other code point below U+0020 is written `\u00xx`, in lowercase hex.
  - Every other code point is written raw as UTF-8, including `/`, U+007F, U+2028, U+2029 and the supplementary
    planes.
  - A lone surrogate is an error in a value and "not canonicalizable" in a stored text.
- **Literals.** `true`, `false`, `null`; `NaN`, `Infinity` and `-Infinity` as is.
- **An integer literal** (`-?\d+`) is written as the integer's decimal, so `-0` becomes `0`.
- **Any other number literal** (with a fraction or an exponent) is written as its **exact decimal value**:
  - plain notation, no exponent;
  - trailing fractional zeros dropped, then a trailing `.`;
  - `-0` written `0`.

  It is computed on the literal's digits, never through a float or a bounded precision: Python's
  `Decimal.normalize()` under the default context rounds to 28 digits, which is wrong here (`format(Decimal(lit),
  "f")` is exact, and agrees). Examples:
  - `238.0` → `238`
  - `4.50` → `4.5`
  - `1E2` → `100`
  - `1e-7` → `0.0000001`
  - `-0.0` → `0`
  - `0.12345678901234567890123456789012345` stays as is.

  The literal's exponent is the integer written after its `e` or `E`. When it is beyond ±1000 (`1e1001`,
  `1e-1001`), the whole text is "not canonicalizable"; `1e1000` is a 1 and a thousand zeros.
- This is exactly `json.dumps(v, sort_keys=True, separators=(",",":"), ensure_ascii=False)` for every value without
  a non-integral number, which keeps FORMAT 1's unit digests unchanged.

Worked by hand, the decimal rule is: take the literal's sign, its digits (integer part then fraction) and the
decimal point's place among them (the integer part's length plus the exponent); pad with zeros on the side the point
falls outside the digits; strip the integer part's leading zeros (keeping one) and the fraction's trailing zeros;
drop an empty fraction's point; write `0` for a zero of either sign.

## Digest `D(v)`

`D(v)` is the lowercase hex SHA-256 of `UTF-8(C(v))`, which is `peer_sync.digest_of`.

## Stored JSON hash `H(text)`

For `versions.raw` and `songs.lyrics_json`:

- SQL `NULL` stays `null`.
- Text that is JSON and canonicalizable: `H = D(parsed)`.
- Otherwise (not JSON, a lone surrogate, an exponent beyond ±1000), `H` is the SHA-256 of the text's bytes, as
  Python's `text.encode("utf-8", "surrogatepass")` gives them. Kotlin hashes those same bytes.

## `kv` text

`PyJson.dumps`, which is not canonical: `db.kv_set_json` writes `json.dumps(value, ensure_ascii=False)`. That is
`", "` and `": "` separators, insertion order, and a number's literal as given. `Db.kvSetJson` writes exactly that,
keeping a `JsonObject`'s order, so every kv record either side writes is byte-identical. This includes the sync
base, which Python builds in `sorted()` key order. `PyJson.dumps(value, sortKeys = true, compact = true)` is
`json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`, the corpus's line format.

## FORMAT 3

FORMAT 3 (the owner's choice of 2026-11-03, "Don't count them for the sync", the M4–6 plan's Q2) changes one thing of
FORMAT 2, below: a version's `raw` is `H(raw)` without what `peer_sync.VOLATILE_RAW` names for its provider, UG's
`rating` and `votes`, which UG's tab page gives as they are the day it is read. `stored_hash(text, without)` (Kotlin's
`Canonical.hashStoredJson(text, without)`) takes those members out of the object the text holds, its own members
alone, before `D`; a text that holds no object, or isn't JSON, is hashed as `H(text)`. `vectors/canonical/
stored_hash_without.jsonl` holds the two to the byte. The state, unit and push documents and the base carry
`"format": 3`, and a base of FORMAT 2 reads as none: the first sync after the upgrade compares as a first sync.

## FORMAT 2

- `peer_sync.FORMAT = 2`. The state, unit and push documents carry `"format": 2`, and a side refuses any other
  format, as today.
- `song_value`'s `versions[].raw` becomes `H(raw)`, and `lyrics[1]` becomes `H(lyrics_json)`. Nothing else in a unit
  value changes.
- The stored base `kv sync:base:<peer id>` becomes `{"format":2,"units":{"<unit id>":[digest|null,"<stamp>"]}}`, and
  `_read_base` reads anything else as no base.
  - There is no translation of a FORMAT 1 base. That would be a compatibility shim, which the owner rules out.
  - The cost: the first sync after the upgrade compares as a first sync. A unit on one side alone is that side's, so
    a song one side removed after their last sync shows as the other side's to take, and the owner flips it to
    "here" in the Sync tab (the plan's §11, question 4).
- The state document gains:
  - `"now"`: the computer's clock, as a stamp. Agreements are stamped with it on both sides, so one clock is used.
  - `"indexes"`: `{site: stamp}`, the newest read time of each site's index on that side. The phone uses it to fetch
    only the sites the computer holds newer.

  Readers ignore keys they don't know, so `cooldowns` can join in M4.

## Vectors

Each row is a stored text, `C` of it (or why there is none) and `H(text)`: `D` of the parsed value when there is a
`C`, else the SHA-256 of the text's own bytes. The text and `C` are written as JSON string literals (Python's
`json.dumps(s)`, ASCII-escaped), so that control characters, the BOM and U+00A0 can be seen; the bytes hashed are
those of the string the literal stands for, in UTF-8. Every row was checked with a scratch script against Python
3.14.7: `json.loads` (whether it reads the text), `json.dumps(…, sort_keys=True, separators=(",",":"),
ensure_ascii=False)` (equal to `C` for every row without a non-integral number), the decimal rule worked by hand and
with `format(Decimal(lit), "f")` (equal for every non-integer literal), and `hashlib.sha256`.

| # | Stored text | `C` | `H` |
|---|---|---|---|
| 1 | `"{\"b\":1,\"a\":2}"` | `"{\"a\":2,\"b\":1}"` | `d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772` |
| 2 | `" {\t\"a\" : [ 1 ,\r\n2 ] }\n"` | `"{\"a\":[1,2]}"` | `01530d164d479cf08e26d3b1ad9bdba927120d97e2d057a6d792db778780d720` |
| 3 | `"{\"a\":[1,2]}"` | `"{\"a\":[1,2]}"` | `01530d164d479cf08e26d3b1ad9bdba927120d97e2d057a6d792db778780d720` |
| 4 | `"{\"z\":{\"b\":[1,{\"y\":1,\"x\":2}],\"a\":null}}"` | `"{\"z\":{\"a\":null,\"b\":[1,{\"x\":2,\"y\":1}]}}"` | `90d26a09639500cf5710eefefca2034bdeefff6dbd1c592be12b8f9281b88794` |
| 5 | `"\"\\u0001\\u001F\""` | `"\"\\u0001\\u001f\""` | `f815f96679a091ead4c530e4c613290cf48dd890f519c2ebc07adc3dcc596641` |
| 6 | `"\"\\u0008\\u0009\\u000a\\u000C\\u000d\""` | `"\"\\b\\t\\n\\f\\r\""` | `6e62a535b04fecef3e63e0a67bc2a0657383132fed040cbe7fcb725ed72bae27` |
| 7 | `"\"\\u007f\""` | `"\"\u007f\""` | `6fe76740e12a93d5598fe685cb6ad3d3c94e44609065a56866b69647772026ec` |
| 8 | `"\"\\u2028\\u2029\""` | `"\"\u2028\u2029\""` | `e3a0e2262ac7790f4df36b522a8fbdd4ee3370d568eb15dc25c5f1775f14ed6c` |
| 9 | `"\"\\/\\u00e9\\\"\""` | `"\"/\u00e9\\\"\""` | `07b9371c2c0f6ec5511235e80a095e8aa1792bc2a0566a7ad018d611bd937add` |
| 10 | `"\"\\ud83c\\udfb8\""` | `"\"\ud83c\udfb8\""` | `a9aa6b507f6596044f6802fa633af74d4998b8950c1938bb54e6d63ec053d416` |
| 11 | `"{\"\\ud83c\\udfb8\":2,\"\\uff61\":1}"` | `"{\"\uff61\":1,\"\ud83c\udfb8\":2}"` | `9217d0ebcdddf167491b9693b8e59f4db62531e6fa658eca50bbd5a10a26c1a5` |
| 12 | `"{\"a\":1,\"a\":2}"` | `"{\"a\":2}"` | `7e8059f495589fcd981232cc11d00b00da3802c01d688fa1cf1f6bed6e5bb33c` |
| 13 | `"[true,false,null]"` | `"[true,false,null]"` | `4d0f18de2133118249c26acc481838d4f6bb6bc1de882d99abbd19ae9397e8df` |
| 14 | `"[NaN,Infinity,-Infinity]"` | `"[NaN,Infinity,-Infinity]"` | `b1ec71618b1e885b866bc52473ebb29432cd8babf979d53a05c12053c0f1a9c9` |
| 15 | `"12345678901234567890123"` | `"12345678901234567890123"` | `0c71ebdc4736bf09a888457750aa22f7c895026afb64b40f8fbd94092c61c19b` |
| 16 | `"-0"` | `"0"` | `5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9` |
| 17 | `"238.0"` | `"238"` | `8ae4c23b80d1e7c8ff79e515fe791ebd68190bae842dda7af193db125f700452` |
| 18 | `"4.50"` | `"4.5"` | `32209ccbf8a8e509b9027698cc173343a2695e8ecdbe899bf5335a3100c956fc` |
| 19 | `"1E2"` | `"100"` | `ad57366865126e55649ecb23ae1d48887544976efea46a48eb5d85a6eeb4d306` |
| 20 | `"1e-7"` | `"0.0000001"` | `4035c4eedb2f0cf061cb4aedac998085c68fc1a1f5a3cc5de86c5086ba770324` |
| 21 | `"-0.0"` | `"0"` | `5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9` |
| 22 | `"-0e-3"` | `"0"` | `5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9` |
| 23 | `"0.12345678901234567890123456789012345"` | `"0.12345678901234567890123456789012345"` | `9949915f171c03f4cb10146de2f8ac0c52110c39eed99259471786d7c2840be7` |
| 24 | `"-12.340e1"` | `"-123.4"` | `b9a75205414983f4bf5f2d64bcb71bb17a1097bbd1732ab566a0cf011858eca8` |
| 25 | `"1.5E-3"` | `"0.0015"` | `14af13ae3e34736b4436d3e1047fe8cad378d86a8324cf7816d6bc473a0885b8` |
| 26 | `"100e-2"` | `"1"` | `6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b` |
| 27 | `"1e30"` | `"1000000000000000000000000000000"` | `fa72d4146f76703a4c9589d4a4af8722b2568665c8f8b8aa773d800e00a12d1f` |
| 28 | `"{\"t\":[238.0,1e-7]}"` | `"{\"t\":[238,0.0000001]}"` | `8ea439a1d355148cd4dacba0730490ef243ec7dacdc04f9d385815133cf9113d` |
| 29 | `"1e999999999"` | not canonicalizable | `0b37a136a0cae8450e3c304656908185b43b2e40bcf4f6fc729f3f9b5860d819` |
| 30 | `"1e1001"` | not canonicalizable | `3cd552a909bb8af60e5a818e6d1f4e8777ecb07a2b820aa19e487f0b63ba7fa6` |
| 31 | `"\"\\ud800\""` | not canonicalizable | `8c0c59dd0d275aadcd462a5fe12eb352cbdfeaf961eae4f85a4660521df7d2f5` |
| 32 | `"1"` × 5000 (a 5000-digit integer) | not JSON | `7329360cc0f6f4b07949591941e2c56fe513672569680b45303fcd13e1ba9ed0` |
| 33 | `"\"a\u0001b\""` | not JSON | `e0b6aa5e22df0d2a12cc3ebd8c821db5ae6cf6d7bcf45646dc2463cd63cb7783` |
| 34 | `"01"` | not JSON | `938db8c9f82c8cb58d3f3ef4fd250036a48d26a712753d2fde5abd03a85cabf4` |
| 35 | `"+1"` | not JSON | `c59dc4e44ff99288156d4dff2168f6ac7ddee6b1fc7ccc0754656ffaa6d351ea` |
| 36 | `".5"` | not JSON | `4b1e53e66b4abd4fa86fe66980fa3affccd4252ec85897c978cf89173b3ad99e` |
| 37 | `"1."` | not JSON | `c977dbe785221d34114d345fdf8ff4e18bb4af66750751dbea29407f9738735f` |
| 38 | `"\ufeff{}"` | not JSON | `aa25e978046d680ef8740d837e6de5bc1e2a2dc6089dbda1012544b538d53f65` |
| 39 | `"{\"a\":1}\u00a0"` | not JSON | `561499e053d66e1798f10f20fcb264c8397b2b62183a7daf301edd9967d4f5d9` |
| 40 | `"hello"` | not JSON | `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824` |
| 41 | `""` | not JSON | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The boundary of the exponent rule, too long for the table: `"1e1000"` is canonicalizable, a 1 and a thousand zeros,
`H` = `4d20ea8840f0be06124aa54cac837707b5259196832785a09391d1f15fda98f9`.

Rows 2 and 3 are one record in two layouts, so one digest; rows 16, 21 and 22 are three zeros, one digest. Row 11 is
the order that differs between code points and UTF-16 (U+FF61 sorts first). Row 32 is refused by Python's int limit,
not by the grammar.
