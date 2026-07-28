#!/usr/bin/env python3
"""test_authorization_profiles.py — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.

Kontaktfreie Tests des Plattformprofil-Modells von authorize.py.

Es werden AUSSCHLIESSLICH temporäre Kopien und Mock-Kommandoausgaben verwendet.
Der echte Kontakte-Sidecar wird NICHT gestartet, es gibt KEINE
Contacts-Operation, KEIN requestAuthorization und KEINEN TCC-Dialog.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import authorize  # noqa: E402
from authorize import CheckError  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

ARM_LEAF = "0139fb6e5a2b9c2c6ade8acc0932bebbb653dbdf"
X86_LEAF = "f378c267e1c065e3dbfc07acb7b922c10651255c"
BUNDLE_ID = "de.jarvis.contacts-spike.sidecar"
USAGE = "Spike-Test: Zugriff auf Kontakte (SIDECAR)"
AUTHORITY = "Personal Jarvis Contacts Spike"


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)[:200]))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}  {str(detail)[:140]}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_profile(arch: str = "arm64", leaf: str | None = None, **over) -> dict:
    leaf = leaf or (ARM_LEAF if arch == "arm64" else X86_LEAF)
    p = {
        "schemaVersion": 1,
        "platform": "macOS",
        "architecture": arch,
        "minimumSystemVersion": "12.3",
        "sidecarRelativePath": "tools/jarvis-contacts",
        "bundleIdentifier": BUNDLE_ID,
        "usageDescription": USAGE,
        "signingAuthority": AUTHORITY,
        "certificateLeafSha1": leaf,
        "designatedRequirement":
            f'identifier "{BUNDLE_ID}" and certificate leaf = H"{leaf}"',
        "hardenedRuntimeRequired": True,
        "entitlementsRequiredEmpty": True,
    }
    p.update(over)
    return p


def build_package(tmp: Path, profile: dict, *, sidecar_bytes: bytes = b"FAKE-SIDECAR",
                  manifest_extra: str = "", profile_bytes: bytes | None = None,
                  omit_profile_hash: bool = False,
                  duplicate_profile_hash: bool = False,
                  wrong_profile_hash: bool = False) -> Path:
    """Baut ein vollstaendiges Fake-Uebergabepaket aus Kopien."""
    root = tmp / f"pkg-{len(list(tmp.iterdir()))}"
    (root / "tools").mkdir(parents=True)
    sidecar = root / "tools" / "jarvis-contacts"
    sidecar.write_bytes(sidecar_bytes)
    sidecar.chmod(0o755)

    pbytes = profile_bytes if profile_bytes is not None else json.dumps(
        profile, indent=2).encode()
    pfile = root / "tools" / "authorization-profile.json"
    pfile.write_bytes(pbytes)
    pfile.chmod(0o644)

    lines = [f"{sha256_bytes(sidecar_bytes)}  ./tools/jarvis-contacts"]
    phash = sha256_bytes(pbytes)
    if wrong_profile_hash:
        phash = "0" * 64
    if not omit_profile_hash:
        lines.append(f"{phash}  ./tools/authorization-profile.json")
        if duplicate_profile_hash:
            lines.append(f"{phash}  ./tools/authorization-profile.json")
    if manifest_extra:
        lines.append(manifest_extra)
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n")
    return root


# ── Mock-Runner fuer codesign/otool/lipo ─────────────────────────────────────
class Res:
    def __init__(self, out: str = "", err: str = "", rc: int = 0):
        self.stdout, self.stderr, self.returncode = out, err, rc


def make_runner(*, dr_leaf: str | None = None, authority: str = AUTHORITY,
                flags: str = "0x10000(runtime)", entitlements: str = "",
                bundle_id: str = BUNDLE_ID, usage: str = USAGE,
                arch: str = "arm64", minos: str = "12.3",
                universal: bool = False, verify_rc: int = 0):
    """Liefert einen Runner, der codesign/otool/lipo glaubwuerdig nachbildet."""
    leaf = dr_leaf or ARM_LEAF
    dr = f'designated => identifier "{bundle_id}" and certificate leaf = H"{leaf}"'

    def runner(cmd: list[str]) -> Res:
        joined = " ".join(cmd)
        if "--verify" in cmd:
            return Res(rc=verify_rc, err="" if verify_rc == 0 else "verify failed")
        if "-r-" in cmd:
            return Res(out=f"Executable=x\n{dr}\n")
        if "--entitlements" in cmd:
            return Res(out=entitlements)
        if "codesign" in joined and "--verbose=4" in joined:
            return Res(out=f"Identifier={bundle_id}\n"
                           f"CodeDirectory v=20500 size=641 flags={flags} "
                           f"hashes=14+2 location=embedded\n"
                           f"Authority={authority}\n")
        if "otool" in joined and "-P" in cmd:
            return Res(out=f"<key>CFBundleIdentifier</key>\n<string>{bundle_id}"
                           f"</string>\n<key>NSContactsUsageDescription</key>\n"
                           f"<string>{usage}</string>\n")
        if "lipo" in joined:
            if universal:
                return Res(out="Architectures in the fat file: x are: x86_64 arm64")
            return Res(out=f"Non-fat file: x is architecture: {arch}")
        if "otool" in joined and "-l" in cmd:
            return Res(out=f"      cmd LC_BUILD_VERSION\n  cmdsize 32\n"
                           f" platform 1\n    minos {minos}\n      sdk 26.5\n")
        return Res()
    return runner


def expect_fail(name: str, fn, needle: str = "") -> None:
    try:
        fn()
    except CheckError as e:
        ok = needle.lower() in str(e).lower() if needle else True
        check(name, ok, f"CheckError: {str(e).splitlines()[0][:110]}")
        return
    except Exception as e:                                    # pragma: no cover
        check(name, False, f"falscher Typ {type(e).__name__}: {e}")
        return
    check(name, False, "kein Fehler — erwartet CheckError")


def expect_ok(name: str, fn, detail: str = "") -> None:
    try:
        fn()
        check(name, True, detail)
    except Exception as e:
        check(name, False, f"{type(e).__name__}: {str(e).splitlines()[0][:110]}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="authprofiles-")).resolve()
    host = authorize.platform.machine()
    other = "x86_64" if host == "arm64" else "arm64"
    host_leaf = ARM_LEAF if host == "arm64" else X86_LEAF

    # 1) gueltiges Host-Profil (arm64 auf arm64 bzw. x86_64 auf Intel)
    prof = make_profile(host, host_leaf)
    root = build_package(tmp, prof)
    runner = make_runner(dr_leaf=host_leaf, arch=host)
    expect_ok("01-gueltiges-profil-host-arch",
              lambda: authorize.preflight(root, runner=runner, quiet=True),
              f"Host={host}")

    # 2) Gleichwertigkeit: dasselbe Modell fuer die andere Architektur.
    #    Der Host-Abgleich muss dort greifen — das belegt, dass der Code die
    #    Architektur ausschliesslich aus dem Profil bezieht.
    prof_other = make_profile(other, X86_LEAF if other == "x86_64" else ARM_LEAF)
    root_other = build_package(tmp, prof_other)
    expect_fail("02-anderes-arch-profil-greift-host-abgleich",
                lambda: authorize.load_profile(root_other, quiet=True),
                "host-architektur")
    # ... und ist ansonsten strukturell gueltig (Schema-Pruefung ohne Host-Check)
    rebuilt = authorize.reconstruct_dr(prof_other["bundleIdentifier"],
                                       prof_other["certificateLeafSha1"])
    check("02b-anderes-arch-profil-strukturell-gueltig",
          rebuilt == prof_other["designatedRequirement"]
          and prof_other["architecture"] in authorize.ALLOWED_ARCHITECTURES,
          f"{other}: DR rekonstruierbar, Architektur erlaubt")

    # 3) Profil fehlt
    r3 = build_package(tmp, prof)
    (r3 / "tools" / "authorization-profile.json").unlink()
    expect_fail("03-profil-fehlt", lambda: authorize.load_profile(r3, quiet=True),
                "fehlt")

    # 4) Profil ist Symlink
    r4 = build_package(tmp, prof)
    p4 = r4 / "tools" / "authorization-profile.json"
    real = r4 / "tools" / "real-profile.json"
    shutil.move(str(p4), str(real))
    p4.symlink_to(real)
    expect_fail("04-profil-ist-symlink",
                lambda: authorize.load_profile(r4, quiet=True), "symlink")

    # 5) Profil ist (fuer Gruppe/andere) beschreibbar
    r5 = build_package(tmp, prof)
    (r5 / "tools" / "authorization-profile.json").chmod(0o666)
    expect_fail("05-profil-beschreibbar",
                lambda: authorize.load_profile(r5, quiet=True), "beschreibbar")

    # 6) Profil-Hash fehlt im Manifest
    r6 = build_package(tmp, prof, omit_profile_hash=True)
    expect_fail("06-profil-hash-fehlt",
                lambda: authorize.load_profile(r6, quiet=True), "kein manifest-eintrag")

    # 7) Profil-Hash doppelt
    r7 = build_package(tmp, prof, duplicate_profile_hash=True)
    expect_fail("07-profil-hash-doppelt",
                lambda: authorize.load_profile(r7, quiet=True), "mehrdeutig")

    # 8) Profil-Hash falsch
    r8 = build_package(tmp, prof, wrong_profile_hash=True)
    expect_fail("08-profil-hash-falsch",
                lambda: authorize.load_profile(r8, quiet=True), "weicht vom manifest ab")

    # 9) unbekannte schemaVersion
    r9 = build_package(tmp, make_profile(host, host_leaf, schemaVersion=2))
    expect_fail("09-unbekannte-schemaversion",
                lambda: authorize.load_profile(r9, quiet=True), "schemaversion")

    # 10) falsche Plattform
    r10 = build_package(tmp, make_profile(host, host_leaf, platform="Linux"))
    expect_fail("10-falsche-plattform",
                lambda: authorize.load_profile(r10, quiet=True), "platform")

    # 11) unzulaessige Architektur
    r11 = build_package(tmp, make_profile(host, host_leaf, architecture="ppc64"))
    expect_fail("11-unzulaessige-architektur",
                lambda: authorize.load_profile(r11, quiet=True), "unzulaessig")

    # 12) Host-Architektur stimmt nicht mit Profil
    r12 = build_package(tmp, make_profile(other, X86_LEAF if other == "x86_64"
                                          else ARM_LEAF))
    expect_fail("12-host-arch-mismatch",
                lambda: authorize.load_profile(r12, quiet=True), "host-architektur")

    # 13) falsche Mindestversion
    r13 = build_package(tmp, make_profile(host, host_leaf,
                                          minimumSystemVersion="13.0"))
    expect_fail("13-falsche-mindestversion",
                lambda: authorize.load_profile(r13, quiet=True), "minimumsystemversion")

    # 14) unsicherer sidecarRelativePath
    for label, bad in (("absolut", "/etc/passwd"),
                       ("dotdot", "tools/../../etc/passwd"),
                       ("fremd", "tools/other-binary")):
        rr = build_package(tmp, make_profile(host, host_leaf,
                                             sidecarRelativePath=bad))
        expect_fail(f"14-unsicherer-pfad-{label}",
                    lambda rr=rr: authorize.load_profile(rr, quiet=True))

    # 15) falscher certificate leaf (Format)
    r15 = build_package(tmp, make_profile(host, host_leaf,
                                          certificateLeafSha1="XYZ"))
    expect_fail("15-leaf-format-falsch",
                lambda: authorize.load_profile(r15, quiet=True), "40 hexadezimale")

    # 16) inkonsistente rekonstruierte DR
    r16 = build_package(tmp, make_profile(
        host, host_leaf,
        designatedRequirement='identifier "de.fremd.app" and certificate leaf = H"'
                              + host_leaf + '"'))
    expect_fail("16-dr-nicht-rekonstruierbar",
                lambda: authorize.load_profile(r16, quiet=True), "rekonstruierbar")

    # 16b) unbekanntes Zusatzfeld (sicherheitsrelevanter Override)
    r16b = build_package(tmp, make_profile(host, host_leaf,
                                           allowAnyCertificate=True))
    expect_fail("16b-unbekanntes-feld",
                lambda: authorize.load_profile(r16b, quiet=True), "unbekannte")

    # ── Sidecar-Pruefungen gegen ein gueltiges Profil ────────────────────────
    good = make_profile(host, host_leaf)
    groot = build_package(tmp, good)
    spath = groot / "tools" / "jarvis-contacts"

    # 17) Sidecar-DR weicht ab
    expect_fail("17-sidecar-dr-weicht-ab",
                lambda: authorize.check_codesign(
                    spath, good, runner=make_runner(dr_leaf="a" * 40), quiet=True),
                "designated requirement")

    # 18) Sidecar-Authority weicht ab
    expect_fail("18-sidecar-authority-weicht-ab",
                lambda: authorize.check_codesign(
                    spath, good,
                    runner=make_runner(dr_leaf=host_leaf, authority="Fremde CA"),
                    quiet=True),
                "signierende instanz")

    # 19) Sidecar ist ad hoc
    expect_fail("19-sidecar-adhoc",
                lambda: authorize.check_codesign(
                    spath, good,
                    runner=make_runner(dr_leaf=host_leaf,
                                       flags="0x10002(adhoc,runtime)"),
                    quiet=True),
                "ad-hoc")

    # 19b) Hardened Runtime fehlt
    expect_fail("19b-hardened-runtime-fehlt",
                lambda: authorize.check_codesign(
                    spath, good,
                    runner=make_runner(dr_leaf=host_leaf, flags="0x0(none)"),
                    quiet=True),
                "hardened runtime")

    # 20) Sidecar besitzt Entitlements
    expect_fail("20-sidecar-hat-entitlements",
                lambda: authorize.check_codesign(
                    spath, good,
                    runner=make_runner(dr_leaf=host_leaf,
                                       entitlements="<key>com.apple.security.x</key>"),
                    quiet=True),
                "entitlements")

    # 21) Sidecar-Architektur weicht ab
    expect_fail("21-sidecar-arch-weicht-ab",
                lambda: authorize.check_platform(
                    spath, good, runner=make_runner(arch=other), quiet=True),
                "architektur")

    # 22) Sidecar ist Universal-Binary
    expect_fail("22-sidecar-universal",
                lambda: authorize.check_platform(
                    spath, good, runner=make_runner(universal=True), quiet=True),
                "universal")

    # 22b) minos weicht ab
    expect_fail("22b-sidecar-minos-weicht-ab",
                lambda: authorize.check_platform(
                    spath, good, runner=make_runner(arch=host, minos="13.0"),
                    quiet=True),
                "mindestversion")

    # 23) Usage-String weicht ab
    expect_fail("23-usage-string-weicht-ab",
                lambda: authorize.check_embedded_identity(
                    spath, good, runner=make_runner(usage="Etwas anderes"),
                    quiet=True),
                "nscontactsusagedescription")

    # 24) Identifier weicht ab
    expect_fail("24-identifier-weicht-ab",
                lambda: authorize.check_embedded_identity(
                    spath, good, runner=make_runner(bundle_id="de.fremd.app"),
                    quiet=True),
                "cfbundleidentifier")

    # 24b) codesign --verify schlaegt fehl
    expect_fail("24b-codesign-verify-fehlgeschlagen",
                lambda: authorize.check_codesign(
                    spath, good, runner=make_runner(dr_leaf=host_leaf, verify_rc=1),
                    quiet=True),
                "verify")

    # 24c) Sidecar-Hash weicht vom Manifest ab
    r24c = build_package(tmp, good)
    (r24c / "tools" / "jarvis-contacts").write_bytes(b"MANIPULIERT")
    expect_fail("24c-sidecar-hash-weicht-ab",
                lambda: authorize.check_sidecar_manifest(r24c, good, quiet=True),
                "weicht vom manifest ab")

    # 25) TOCTOU: Profil nach der Pruefung veraendert
    r25 = build_package(tmp, good)
    _, pdigest = authorize.load_profile(r25, quiet=True)
    (r25 / "tools" / "authorization-profile.json").write_bytes(b'{"x":1}')
    after = authorize.sha256_of(r25 / "tools" / "authorization-profile.json")
    check("25-toctou-profil-erkennbar", after != pdigest,
          f"vorher {pdigest[:12]} != nachher {after[:12]}")

    # 26) TOCTOU: Sidecar nach der Pruefung veraendert
    r26 = build_package(tmp, good)
    sdigest = authorize.check_sidecar_manifest(r26, good, quiet=True)
    (r26 / "tools" / "jarvis-contacts").write_bytes(b"NEU")
    after_s = authorize.sha256_of(r26 / "tools" / "jarvis-contacts")
    check("26-toctou-sidecar-erkennbar", after_s != sdigest,
          f"vorher {sdigest[:12]} != nachher {after_s[:12]}")

    # 27) Gueltige Vorpruefung endet VOR requestAuthorization
    sent: list[str] = []

    class SpySidecar:                       # pragma: no cover - darf nie starten
        def __init__(self, *a, **k):
            sent.append("STARTED")

    orig = authorize.Sidecar
    authorize.Sidecar = SpySidecar
    try:
        authorize.preflight(groot, runner=make_runner(dr_leaf=host_leaf, arch=host),
                            quiet=True)
    finally:
        authorize.Sidecar = orig
    check("27-preflight-startet-keinen-sidecar", sent == [],
          "kein Sidecar-Start, kein requestAuthorization")

    # Zusatz: keine harte Verdrahtung von Architektur/Leaf im Quelltext
    src = Path(authorize.__file__).read_text()
    check("28-keine-hartverdrahtete-arch",
          'EXPECTED_ARCH' not in src and '"x86_64"' not in src.replace(
              'ALLOWED_ARCHITECTURES = ("arm64", "x86_64")', ''),
          "keine EXPECTED_ARCH-Konstante")
    check("29-kein-hartverdrahteter-leaf",
          ARM_LEAF not in src and X86_LEAF not in src,
          "kein Zertifikats-Fingerprint im Quelltext")

    shutil.rmtree(tmp, ignore_errors=True)

    ok_n = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n--- {ok_n}/{len(RESULTS)} bestanden")
    print("Es wurde KEIN Sidecar gestartet, KEIN requestAuthorization gesendet, "
          "KEIN TCC-Dialog ausgeloest und KEIN Kontakt beruehrt.")
    return 0 if ok_n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
