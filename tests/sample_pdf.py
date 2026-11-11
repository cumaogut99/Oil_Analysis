"""Testler için SGS rapor düzenini taklit eden sentetik PDF üreteci."""
from __future__ import annotations

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SYMBOL_ROWS = ["Ba", "Ca", "Mg", "Mo", "P", "Zn", "B", "K", "Si", "Na", "Al", "Cr",
               "Cu", "Fe", "Pb", "Ni", "Ag", "Sn", "Ti", "V"]
TURKISH_ROWS = ["Baryum", "Kalsiyum", "Magnezyum", "Molibden", "Fosfor", "Cinko", "Bor",
                "Silisyum", "Sodyum", "Aluminyum", "Krom", "Bakir", "Demir", "Kursun",
                "Nikel", "Gumus", "Kalay", "Titanyum", "Vanadyum", "K"]
TR2SYM = dict(zip(TURKISH_ROWS, ["Ba", "Ca", "Mg", "Mo", "P", "Zn", "B", "Si", "Na", "Al",
                                 "Cr", "Cu", "Fe", "Pb", "Ni", "Ag", "Sn", "Ti", "V", "K"]))


def make_report(path, samples, turkish=False, drift=0.0, main=None, motor="TMS22027",
                diag="Yesil", comment="Tum sonuclar kabul edilebilir seviyelerdedir.",
                extra_rows=None):
    """samples: list of dict(sample_no, date, eq, lub, values={key:value})"""
    main = main or samples[-1]["sample_no"]
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    # ---------------- sayfa 1
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, H - 60, f"Test report : {main}")
    c.setFont("Helvetica", 8)
    y = H - 100
    left = [("Registration Nr. :", "02499574"), ("Component :", "AMOT"),
            ("Equipment Desc. :", motor), ("Component Desc. :", "MOTOR"),
            ("Fleet Nr :", "0010938597"), ("Ref. ID :", "ANA931")]
    right = [("Sample Nr :", main), ("Date Sample taken :", samples[-1]["date"]),
             ("Received date :", "08/09/2026"), ("Date of Analysis :", "09/09/2026"),
             ("Lubricant in Use :", "SPEEDOL AERO TURBO DIESEL SP1"),
             ("Equipment (h) :", samples[-1]["eq"]), ("Lubricant (h) :", samples[-1]["lub"])]
    for i in range(max(len(left), len(right))):
        if i < len(left):
            c.drawString(40, y, f"{left[i][0]} {left[i][1]}")
        if i < len(right):
            c.drawString(320, y, f"{right[i][0]} {right[i][1]}")
        y -= 12
    c.drawString(40, y - 10, "Technician: Yavuz Murat      Administration: x")
    # geçmiş tablosu
    y -= 50
    xs = [200 + i * 62 for i in range(6)]
    offset = 6 - len(samples)
    rows = [("Sample Number", "sample_no"), ("Date Sample taken", "date"),
            ("Equipment life (h)", "eq"), ("Lubricant life (h)", "lub"), ("Top-up (gallon)", None)]
    for label, key in rows:
        c.drawString(40, y, label)
        for i, s in enumerate(samples):
            c.drawCentredString(xs[i + offset], y, str(s[key]) if key else "0")
        y -= 12
    c.drawString(40, y - 40, "Wear Upper   Wear Lower")
    y -= 90
    c.drawString(40, y, "Diagnosis")
    for i, s in enumerate(samples):
        c.drawCentredString(xs[i + offset], y, s.get("letter", "Y"))
    y -= 16
    c.setFont("Helvetica-Bold", 9)
    c.drawString(250, y, f"Diagnosis {diag} 09/09/2026")
    c.setFont("Helvetica", 8)
    y -= 14
    c.drawString(45, y, comment)
    y -= 40
    c.drawString(45, y, "Analysed by : SGS OCM Turkey")
    c.showPage()

    # ---------------- sayfa 2: sonuçlar
    c.setFont("Helvetica", 7)
    y = H - 60
    c.drawString(250, y, "RESULTS")
    y -= 14

    def row(label, vals, header=False, bold=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if (header or bold) else "Helvetica", 7)
        c.drawString(40 if header else 50, y, label)
        if vals is not None:
            for i, v in enumerate(vals):
                if v is None:
                    continue
                c.drawCentredString(xs[i + offset], y - drift * row.k, str(v))
        row.k += 1
        y -= 11
    row.k = 0

    row("Sequential number", [str(len(samples) - 1 - i) for i in range(len(samples))])
    row("Sample Number", [s["sample_no"] for s in samples])
    row("Test suite", ["V40+V100+VI+TBN+OIL1" for _ in samples])
    row("Date Sample taken", [s["date"] for s in samples])
    row("Equipment life (h)", [s["eq"] for s in samples])
    row("Lubricant life (h)", [s["lub"] for s in samples])
    row("Viskozite @40°C ,ASTM D7279:20", None, header=True)
    row("Viskozite 40°C mm²/s", [s["values"].get("visc40") for s in samples])
    row("Viskozite @100°C,ASTM D7279:20", None, header=True)
    row("Viskozite 100°C mm²/s", [s["values"].get("visc100") for s in samples])
    row("Toplam Baz Sayısı, ASTM D2896", None, header=True)
    row("TBN mg KOH/g", [s["values"].get("tbn") for s in samples])
    row("Yağ Analizörü, ASTM E2412:2023", None, header=True)
    row("Diesel %", [s["values"].get("diesel") for s in samples])
    row("Nitration A/cm", [s["values"].get("nitration") for s in samples])
    row("Su içerigi %", [s["values"].get("water_pct") for s in samples])
    row("Spektrometri, ASTM D5185", None, header=True)
    for name in (TURKISH_ROWS if turkish else SYMBOL_ROWS):
        key = (TR2SYM[name] if turkish else name).lower()
        row(f"{name} mg/kg", [s["values"].get(key) for s in samples])
    row("PQ Indeks, ASTM D8184:2018", None, header=True)
    row("PQ Index (WPI)", [s["values"].get("pq") for s in samples])
    for label, vals in (extra_rows or []):
        row(label, vals)
    row("End of Analytical Results", None, header=True)
    c.showPage()
    c.save()
