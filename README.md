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
- **İstatistikten hariç tutma:** Absürt değerler ortalama, min/max, limit, artış hızı ve korelasyon hesaplarından çıkarılabilir; değerler silinmez.
  - İstatistik & Limitler sayfasındaki değer inceleme panelinden tek tek veya önerilen uç değerler olarak (dayanıklı z-skoru > 3.5)
  - Numune detayındaki "İst. hariç" sütunundan; ya da numunenin tamamı için
  - Her karar nedeniyle birlikte veritabanında saklanır ve Excel çıktısındaki "Hariç Tutulanlar" sayfasında listelenir.
- **Malzeme kaynakları ve parça tahmini:** Malzeme Kaynakları sayfasında her element için olası kaynak parçalar yazılır (isteğe bağlı genel literatür önerileriyle). Numune detayındaki "Parça Tahmini" sekmesi:
  - Önceki numuneye göre anlamlı artan veya uyarı/alarm veren malzemeleri listeler.
  - Kaynak parçaları puanlar. Birden çok malzemenin işaret ettiği parça (ör. Fe + Cr → segman) üst sıraya çıkar.
- **Sınıflandırma:** platform kodu (C9, C10…) → grup (Baykar / TUSAŞ / TEI), yağ tipi, numune tipi (Rodaj / Green / Saha / Sıfır Yağ / Diğer).
- **Sayfalar:**
  - Numuneler
  - Trend: tek motor veya filtrelenmiş tüm motorlar
  - İstatistik & Limitler: Excel'e aktarılabilir
  - İlişkiler: korelasyon ısı haritası ve dağılım grafiği
  - Malzeme Kaynakları
- **Excel'e dışa aktarma:** renklendirilmiş geniş format, yorumlar ve uzun format sayfaları.
- **Veritabanı:** tek `.db` dosyası (varsayılan: `Belgeler/YagAnalizi/yag_analizi.db`); menüden yedeklenebilir veya başka bir dosya açılabilir.

## Tasarım dosyaları (tema)

Arayüzün görünümü koddan ayrıdır; tamamı `oil_analysis/ui/assets/` altındaki harici dosyalardan yüklenir:

| Dosya | İçerik |
|---|---|
| `style.qss` | Tüm bileşen stilleri (QSS şablonu, `{{token}}` alanları temadan doldurulur) |
| `themes/light.json`, `themes/dark.json` | Renk, yazı tipi, köşe yuvarlaklığı, durum renkleri gibi tasarım token'ları |
| `icons/*.svg` | Çizgi ikonlar (`currentColor` temaya göre renklendirilir) |
| `mpl/light.mplstyle`, `mpl/dark.mplstyle` | Grafik stilleri |

Yeni tema eklemek için `themes/` altına bir `.json` ve `mpl/` altına aynı adlı bir `.mplstyle` dosyası koymanız yeterlidir. Tema, Görünüm menüsünde otomatik olarak listelenir. Açık/koyu geçişi kenar menüsünden yapılır ve seçim hatırlanır.

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
pyinstaller --noconfirm --windowed --onefile --name YagAnalizi ^
  --add-data "oil_analysis/ui/assets;oil_analysis/ui/assets" run.py
```

`--add-data` satırı tasarım dosyalarını (tema, ikon, stil) exe'ye ekler; bu satır olmadan arayüz stilsiz açılır.

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
