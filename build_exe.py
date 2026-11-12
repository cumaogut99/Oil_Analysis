"""Motor Yağı Analiz - kurulum ve tek dosya .exe oluşturma betiği.

Kullanım (Python 3.8 ile):
    py -3.8 build_exe.py                 -> ortamı kurar ve dist\\YagAnalizi.exe oluşturur
    py -3.8 build_exe.py --download-wheels -> internetli bir bilgisayarda paketleri
                                              wheels\\ klasörüne indirir (çevrimdışı kurulum için)

Ne yapar:
  1. Proje klasöründe ayrı bir sanal ortam (build_env) oluşturur; sistem Python'una dokunmaz.
  2. requirements-py38.txt ve requirements-build.txt'deki sabit sürümleri kurar.
     wheels\\ klasörü varsa internete çıkmadan oradan kurar.
  3. PyInstaller ile tek dosya (onefile), konsolsuz exe üretir; tasarım dosyalarını ekler.
  4. Üretilen exe'yi --selftest ile çalıştırıp doğrular.
Tüm çıktı build\\build_log.txt dosyasına da yazılır.
"""
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_DIR = os.path.join(ROOT, "build_env")
WHEELS = os.path.join(ROOT, "wheels")
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
APP_NAME = "YagAnalizi"
REQS = [os.path.join(ROOT, "requirements-py38.txt"), os.path.join(ROOT, "requirements-build.txt")]
IS_WIN = os.name == "nt"

os.makedirs(BUILD, exist_ok=True)
_log = open(os.path.join(BUILD, "build_log.txt"), "w", encoding="utf-8")


def log(msg=""):
    print(msg, flush=True)
    _log.write(msg + "\n")
    _log.flush()


def header(msg):
    log("")
    log("=" * 70)
    log("  " + msg)
    log("=" * 70)


def run(cmd, cwd=ROOT, check=True, env=None):
    log("> " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=env, universal_newlines=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        log("  " + line.rstrip())
    rc = p.wait()
    if check and rc != 0:
        raise SystemExit("\nHATA: komut başarısız oldu (çıkış kodu %d). Ayrıntı: build\\build_log.txt" % rc)
    return rc


def venv_python():
    if IS_WIN:
        return os.path.join(ENV_DIR, "Scripts", "python.exe")
    return os.path.join(ENV_DIR, "bin", "python")


def check_python():
    v = sys.version_info
    log("Python: %s (%s)" % (sys.version.split()[0], sys.executable))
    if v < (3, 8):
        raise SystemExit("HATA: Python 3.8 veya üzeri gerekir.")
    if (v.major, v.minor) != (3, 8):
        log("UYARI: Paket sürümleri Python 3.8 için sabitlendi; %d.%d ile denenecek." % (v.major, v.minor))
    if not IS_WIN:
        log("UYARI: Windows dışında çalışıyorsunuz; üretilen dosya bu işletim sistemine ait olur.")


def have_wheels():
    return os.path.isdir(WHEELS) and any(f.endswith(".whl") for f in os.listdir(WHEELS))


def pip_source_args():
    if have_wheels():
        log("Çevrimdışı kurulum: paketler wheels\\ klasöründen kurulacak.")
        return ["--no-index", "--find-links", WHEELS]
    log("Paketler internetten (PyPI) indirilecek. Şirket ağında proxy gerekiyorsa önce:")
    log("   set HTTPS_PROXY=http://kullanici:sifre@proxy:port")
    return []


def create_env():
    header("1/4  Sanal ortam (build_env)")
    py = venv_python()
    if os.path.exists(py):
        out = subprocess.run([py, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
                             stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        want = "%d.%d" % sys.version_info[:2]
        if out == want:
            log("Mevcut ortam kullanılıyor (Python %s)." % out)
            return py
        log("Ortam farklı Python sürümüyle (%s) oluşturulmuş; yeniden oluşturuluyor." % out)
        shutil.rmtree(ENV_DIR)
    run([sys.executable, "-m", "venv", ENV_DIR])
    return py


def install(py):
    header("2/4  Paketlerin kurulumu")
    src = pip_source_args()
    if not src:
        run([py, "-m", "pip", "install", "--upgrade", "pip"], check=False)
    cmd = [py, "-m", "pip", "install", "--disable-pip-version-check"] + src
    for r in REQS:
        cmd += ["-r", r]
    run(cmd)


def make_icon(py):
    """SVG logodan .ico üretir (başarısız olursa varsayılan ikonla devam edilir)."""
    ico = os.path.join(BUILD, "app_icon.ico")
    svg = os.path.join(ROOT, "oil_analysis", "ui", "assets", "icons", "drop.svg")
    code = (
        "import sys\n"
        "from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor\n"
        "from PySide6.QtSvg import QSvgRenderer\n"
        "from PySide6.QtCore import QByteArray, Qt\n"
        "app = QGuiApplication(['x'])\n"
        "data = open(sys.argv[1], encoding='utf-8').read().replace('currentColor', '#2563eb')\n"
        "r = QSvgRenderer(QByteArray(data.encode('utf-8')))\n"
        "img = QImage(256, 256, QImage.Format_ARGB32)\n"
        "img.fill(Qt.transparent)\n"
        "p = QPainter(img); p.setRenderHint(QPainter.Antialiasing)\n"
        "p.setBrush(QColor('#0f172a')); p.setPen(Qt.NoPen); p.drawRoundedRect(0, 0, 256, 256, 48, 48)\n"
        "r.render(p, img.rect().adjusted(40, 40, -40, -40)); p.end()\n"
        "sys.exit(0 if img.save(sys.argv[2]) else 1)\n"
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    rc = run([py, "-c", code, svg, ico], check=False, env=env)
    return ico if rc == 0 and os.path.exists(ico) else None


def build(py):
    header("3/4  Exe oluşturma (PyInstaller, onefile)")
    assets = os.path.join(ROOT, "oil_analysis", "ui", "assets")
    cmd = [py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", APP_NAME,
           "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyinstaller"),
           "--specpath", BUILD,
           "--add-data", assets + os.pathsep + "oil_analysis/ui/assets",
           "--collect-data", "pdfminer",
           "--collect-data", "docx",
           "--collect-data", "reportlab",
           "--collect-all", "pypdfium2",
           "--hidden-import", "PySide6.QtSvg",
           "--exclude-module", "tkinter", "--exclude-module", "PyQt5",
           "--exclude-module", "PyQt6", "--exclude-module", "PySide2",
           "--exclude-module", "pytest", "--exclude-module", "IPython"]
    ico = make_icon(py)
    if ico:
        cmd += ["--icon", ico]
    cmd.append(os.path.join(ROOT, "run.py"))
    run(cmd)
    exe = os.path.join(DIST, APP_NAME + (".exe" if IS_WIN else ""))
    if not os.path.exists(exe):
        raise SystemExit("HATA: exe oluşmadı. Ayrıntı: build\\build_log.txt")
    return exe


def selftest(exe):
    header("4/4  Doğrulama (exe --selftest)")
    out = os.path.join(BUILD, "selftest.txt")
    if os.path.exists(out):
        os.remove(out)
    t0 = time.time()
    try:
        rc = subprocess.run([exe, "--selftest", out], timeout=300).returncode
    except subprocess.TimeoutExpired:
        log("UYARI: self-test zaman aşımına uğradı.")
        return False
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            for line in f:
                log("  " + line.rstrip())
    log("  (%.0f sn)" % (time.time() - t0))
    return rc == 0


def download_wheels():
    header("Çevrimdışı kurulum için paket indirme (Windows 64-bit, Python 3.8)")
    os.makedirs(WHEELS, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "-d", WHEELS,
           "--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.8",
           "--implementation", "cp", "--abi", "cp38", "--abi", "abi3", "--abi", "none"]
    for r in REQS:
        cmd += ["-r", r]
    run(cmd)
    log("")
    log("Tamamlandı. 'wheels' klasörünü projeyle birlikte internetsiz bilgisayara kopyalayın;")
    log("build_exe.py orada otomatik olarak bu klasörden kuracaktır.")


def main():
    header("Motor Yağı Analiz - kurulum ve exe oluşturma")
    check_python()
    if "--download-wheels" in sys.argv:
        download_wheels()
        return 0
    py = create_env()
    install(py)
    exe = build(py)
    ok = selftest(exe)
    size = os.path.getsize(exe) / (1024 * 1024)
    header("TAMAMLANDI" if ok else "EXE OLUŞTU, ANCAK DOĞRULAMA HATALI")
    log("Exe: %s  (%.0f MB)" % (exe, size))
    if ok:
        log("Bu tek dosyayı istediğiniz bilgisayara kopyalayıp çalıştırabilirsiniz;")
        log("Python kurulu olması gerekmez. Veritabanı: Belgeler\\YagAnalizi\\yag_analizi.db")
    else:
        log("build\\selftest.txt ve build\\build_log.txt dosyalarını kontrol edin.")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        _log.close()
