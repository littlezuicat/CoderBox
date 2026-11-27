# -*- coding: utf-8 -*-
"""读取 Bitwarden / Chrome / Edge / Firefox 的导出文件，整理成保险库条目。全部在本机完成，内容不写日志。
浏览器（Chrome/Edge/Firefox）只支持它们自己导出的 .csv：新版浏览器的密码库有“应用绑定加密”，别的程序读不了，所以不直接读浏览器的数据库。
Bitwarden 支持：
  · .json（未加密）          —— Bitwarden 导出时选“.json”
  · .json（密码保护的加密）  —— 导出时选“.json (Encrypted)” → “Password protected”，并设一个文件密码（推荐：明文不落盘）
  · .csv                     —— 导出时选“.csv”
不支持“账户限定”的加密导出（那种只能导回同一个 Bitwarden 账户）。
没有对应字段的数据不会丢：二步验证密钥(TOTP)、自定义字段、多余的网址、银行卡/身份信息都会写进“备注”里。"""
import base64
import csv
import hashlib
import hmac
import io
import json

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from majing.core.vault import VaultError


class NeedPassword(VaultError):
    """这是密码保护的加密导出，需要文件密码。"""


# ---------------------------------------------------------------- 加密导出
def _unb64(s):
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _dec_encstring(s, enc_key, mac_key):
    """Bitwarden 的 EncString：'2.<iv>|<密文>|<mac>'（AES-256-CBC + HMAC-SHA256），先验 mac 再解密。"""
    if not isinstance(s, str) or not s.startswith("2."):
        raise VaultError("这个导出文件用了不认识的加密格式。")
    try:
        iv, ct, mac = [_unb64(x) for x in s[2:].split("|")]
    except Exception:                                        # noqa: BLE001
        raise VaultError("导出文件里的加密数据格式不对。")
    want = hmac.new(mac_key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(want, mac):
        raise VaultError("文件密码不对，或者文件已损坏。")
    dec = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    un = padding.PKCS7(128).unpadder()
    return un.update(padded) + un.finalize()


def _derive_keys(doc, password):
    salt = str(doc.get("salt", ""))
    kdf = int(doc.get("kdfType", 0) or 0)
    pw = password.encode("utf-8")
    if kdf == 0:
        master = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt.encode("utf-8"), iterations=int(doc.get("kdfIterations") or 600000)).derive(pw)
    elif kdf == 1:
        master = Argon2id(salt=hashlib.sha256(salt.encode("utf-8")).digest(), length=32, iterations=int(doc.get("kdfIterations") or 3),
                          lanes=int(doc.get("kdfParallelism") or 4), memory_cost=int(doc.get("kdfMemory") or 64) * 1024).derive(pw)
    else:
        raise VaultError("这个导出文件的密钥算法不认识。")
    enc = HKDFExpand(algorithm=hashes.SHA256(), length=32, info=b"enc").derive(master)
    mac = HKDFExpand(algorithm=hashes.SHA256(), length=32, info=b"mac").derive(master)
    return enc, mac


def decrypt_export(doc, password):
    if not doc.get("passwordProtected"):
        raise VaultError("这是“账户限定”的加密导出，只能导回原来的 Bitwarden 账户。请重新导出：选 .json（未加密）或“密码保护”的加密 .json。")
    if not password:
        raise NeedPassword("这个导出文件有密码，请输入导出时设置的文件密码。")
    enc, mac = _derive_keys(doc, password)
    try:
        _dec_encstring(doc["encKeyValidation_DO_NOT_EDIT"], enc, mac)     # 先用校验串确认密码对不对
    except VaultError:
        raise VaultError("文件密码不对。（注意是导出时设置的“文件密码”，不是 Bitwarden 主密码，除非你设的是同一个。）")
    return json.loads(_dec_encstring(doc["data"], enc, mac).decode("utf-8"))


# ---------------------------------------------------------------- 整理条目
def _lines(*pairs):
    return [("%s：%s" % (k, v)) for k, v in pairs if v not in (None, "")]


def _from_item(it, folders):
    t = it.get("type")
    login = it.get("login") or {}
    notes = [str(it.get("notes") or "")]
    extra = []
    uris = [u.get("uri") for u in (login.get("uris") or []) if u.get("uri")]
    url = uris[0] if uris else ""
    if len(uris) > 1:
        extra += _lines(*[("网址", u) for u in uris[1:]])
    if login.get("totp"):
        extra += _lines(("二步验证密钥(TOTP)", login["totp"]))
    extra += _lines(*[(f.get("name") or "字段", f.get("value")) for f in (it.get("fields") or [])])
    kind = "login"
    if t == 3:
        c = it.get("card") or {}
        kind = "note"
        extra = _lines(("类型", "银行卡"), ("持卡人", c.get("cardholderName")), ("卡品牌", c.get("brand")), ("卡号", c.get("number")),
                       ("有效期", "/".join(x for x in (c.get("expMonth"), c.get("expYear")) if x)), ("安全码", c.get("code"))) + extra
    elif t == 4:
        i = it.get("identity") or {}
        kind = "note"
        name = " ".join(x for x in (i.get("title"), i.get("firstName"), i.get("middleName"), i.get("lastName")) if x)
        addr = " ".join(x for x in (i.get("address1"), i.get("address2"), i.get("address3"), i.get("city"), i.get("state"), i.get("postalCode"), i.get("country")) if x)
        extra = _lines(("类型", "身份信息"), ("姓名", name), ("公司", i.get("company")), ("邮箱", i.get("email")), ("电话", i.get("phone")), ("证件号/社保号", i.get("ssn")),
                       ("护照号", i.get("passportNumber")), ("驾照号", i.get("licenseNumber")), ("用户名", i.get("username")), ("地址", addr)) + extra
    elif t == 5:
        s = it.get("sshKey") or {}
        kind = "note"
        extra = _lines(("类型", "SSH 密钥"), ("公钥", s.get("publicKey")), ("私钥", s.get("privateKey")), ("指纹", s.get("keyFingerprint"))) + extra
    elif t == 2:
        kind = "note"
    text = "\n".join(x for x in notes if x)
    if extra:
        text = (text + "\n\n" if text else "") + "\n".join(extra)
    return {"type": kind, "name": it.get("name") or "", "username": login.get("username") or "", "password": login.get("password") or "", "url": url,
            "notes": text, "folder": folders.get(it.get("folderId") or "", "")}


def from_json(doc):
    folders = {f.get("id"): f.get("name", "") for f in (doc.get("folders") or [])}
    return [_from_item(it, folders) for it in (doc.get("items") or [])]


def from_csv(text):
    rdr = csv.DictReader(io.StringIO(text))
    need = {"name", "login_uri", "login_username", "login_password"}
    if not rdr.fieldnames or not need.issubset(set(rdr.fieldnames)):
        raise VaultError("这个 CSV 不是 Bitwarden 的导出格式（缺少 name / login_username 等列）。")
    out = []
    for r in rdr:
        t = (r.get("type") or "login").strip().lower()
        notes = r.get("notes") or ""
        extra = []
        uris = [u for u in (r.get("login_uri") or "").split("\n") if u.strip()]
        if len(uris) > 1:
            extra += _lines(*[("网址", u) for u in uris[1:]])
        if r.get("login_totp"):
            extra += _lines(("二步验证密钥(TOTP)", r["login_totp"]))
        if (r.get("fields") or "").strip():
            extra += [x for x in r["fields"].split("\n") if x.strip()]
        text = notes + (("\n\n" if notes else "") + "\n".join(extra) if extra else "")
        out.append({"type": "note" if t != "login" else "login", "name": r.get("name") or "", "username": r.get("login_username") or "", "password": r.get("login_password") or "",
                    "url": uris[0] if uris else "", "notes": text, "folder": r.get("folder") or ""})
    return out


def _host_of(url):
    from urllib.parse import urlsplit
    u = (url or "").strip()
    try:
        h = urlsplit(u if "://" in u else "https://" + u).hostname or ""
    except ValueError:
        h = ""
    return h[4:] if h.startswith("www.") else h


def from_browser_csv(text):
    """Chrome / Edge / Firefox 导出的密码 CSV：
       Chrome  name,url,username,password,note        Edge  name,url,username,password
       Firefox url,username,password,httpRealm,formActionOrigin,guid,timeCreated,...（没有 name，用网站域名当名称）"""
    rdr = csv.DictReader(io.StringIO(text))
    rdr.fieldnames = [(f or "").strip().lower() for f in (rdr.fieldnames or [])]
    out = []
    for r in rdr:
        url, user, pw = (r.get("url") or "").strip(), r.get("username") or "", r.get("password") or ""
        if not url and not user and not pw:
            continue
        name = (r.get("name") or "").strip() or _host_of(url) or url
        out.append({"type": "login", "name": name, "username": user, "password": pw, "url": url, "notes": r.get("note") or "", "folder": ""})
    return out


def load(path, password=""):
    return load_ex(path, password)[0]


def load_ex(path, password=""):
    """读文件，返回 (条目列表, 来源)。来源：bitwarden / browser。错误都是 VaultError（NeedPassword 表示要文件密码）。"""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise VaultError("读不了这个文件：%s" % type(e).__name__)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise VaultError("文件不是 UTF-8 文本，不像是 Bitwarden 的导出。")
    s = text.lstrip()
    if s.startswith("{"):
        try:
            doc = json.loads(s)
        except ValueError:
            raise VaultError("JSON 文件读不了（格式不对）。")
        if doc.get("encrypted"):
            doc = decrypt_export(doc, password)
        elif not isinstance(doc.get("items"), list):
            raise VaultError("这个 JSON 里没有 items，不像是 Bitwarden 的导出。")
        return from_json(doc), "bitwarden"
    head = {(h or "").strip().lower() for h in (next(csv.reader(io.StringIO(s)), []) or [])}
    if "login_uri" in head:
        return from_csv(text), "bitwarden"
    if {"url", "username", "password"} <= head:
        return from_browser_csv(text), "browser"
    raise VaultError("这个 CSV 认不出来。支持 Bitwarden、Chrome、Edge、Firefox 导出的密码文件。")
