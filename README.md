# Motor Yağı Analiz

SGS yağ analizi PDF raporlarını okuyup tek bir SQLite veritabanında toplayan,
istatistik/limit hesaplayan ve trendleri gösteren **tamamen çevrimdışı** masaüstü uygulaması
(Python + PySide6).

## Özellikler

- **PDF okuma:** SGS raporlarındaki tüm sayfalar okunur.
  - Ana numunenin yanında, rapordaki geçmiş numune sütunları da okunur.
  - 1. sayfadaki bilgiler, SGS teşhisi ve yorumu ayrıca saklanır.
  - Rapor formatı değişse de okuma bozulmaz: Ca / Kalsiyum gibi farklı yazımlar, farklı satır sırası, eksik sütunlar, "IMP" değerleri ve virgüllü sayılar işlenir.
  - Tanınmayan satırlar kullanıcıya sorulur ve verilen eşleştirme sonraki raporlar için hatırlanır.
- **Geçmiş Excel'i içe aktarma:** `YAG_ANALIZI_FULL.xlsx` düzenindeki dosyalar okunur.
  - Birleştirilmiş hücreler (ör. Motor Numarası) her sütuna dağıtılır.
  - "SIFIR YAĞ" sütunu taze yağ referansı olarak alınır.
  - MAX/MIN/AVR sütunları atlanır.
- **Değerlendirme:** her ölçüm Normal / Uyarı / Alarm olarak sınıflanır. Kurallar:
  - Sabit limitler
  - Yağ sınıfına göre viskozite aralığı
  - Taze yağa göre değişim (katkı tükenmesi, viskozite, TBN)
  - İstatistiksel limitler (ASTM D7720 yaklaşımı)
  - Artış hızı, ppm/100 sa (JOAP yaklaşımı)

  Ayrıntılar uygulamada **Yardım > Değerlendirme yöntemleri** menüsündedir.
- **Kullanıcı yorumu:** Her numune için ayrı bir değerlendirme alanı vardır. SGS teşhisi yalnızca bilgi amaçlı gösterilir.
- **Sınıflandırma:** platform kodu (C9, C10…) → grup (Baykar / TUSAŞ / TEI), yağ tipi, numune tipi (Rodaj / Green / Saha / Sıfır Yağ / Diğer).
- **Sekmeler:**
  - Numuneler
  - Trend: tek motor veya filtrelenmiş tüm motorlar
  - İstatistik & Limitler: Excel'e aktarılabilir
  - İlişkiler: korelasyon ısı haritası ve dağılım grafiği
- **Excel'e dışa aktarma:** renklendirilmiş geniş format, yorumlar ve uzun format sayfaları.
- **Veritabanı:** tek `.db` dosyası (varsayılan: `Belgeler/YagAnalizi/yag_analizi.db`); menüden yedeklenebilir veya başka bir dosya açılabilir.

## Kurulum (geliştirme)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## Tek dosya .exe oluşturma

```bat
pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name YagAnalizi run.py
```

Çıktı `dist\YagAnalizi.exe` olur. Açılışın daha hızlı olması için `--onefile` yerine
`--onedir` kullanılabilir (klasör halinde dağıtılır).

## Taranmış PDF'ler için OCR (opsiyonel)

Raporlar normalde metin içerir ve OCR gerekmez. Taranmış bir PDF gelirse:

1. Tesseract programını Türkçe ve İngilizce dil paketleriyle kurun.
2. `pip install pytesseract` komutunu çalıştırın.

Uygulama bu durumda OCR'a otomatik olarak geçer.

## Testler

```bash
pip install pytest reportlab
python -m pytest tests
```

Testler sentetik SGS düzeninde PDF ve Excel üretip ayrıştırıcıları doğrular. Sentetik PDF'ler şu durumları kapsar:
- Sembol ve Türkçe element adları
- Tek ve çok sütun
- Satır kayması
- Tanınmayan satır
