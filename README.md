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
- **İstatistikten hariç tutma:** Absürt değerler ortalama, min/max, limit ve artış hızı hesaplarından çıkarılabilir; değerler silinmez.
  - İstatistik & Limitler sayfasındaki değer inceleme panelinden tek tek veya önerilen uç değerler olarak (dayanıklı z-skoru > 3.5)
  - Numune detayındaki "İst. hariç" sütunundan; ya da numunenin tamamı için
  - Her karar nedeniyle birlikte veritabanında saklanır ve Excel çıktısındaki "Hariç Tutulanlar" sayfasında listelenir.
- **Malzeme kaynakları ve parça tahmini:** Malzeme Kaynakları sayfasında her element için olası kaynak parçalar yazılır (isteğe bağlı genel literatür önerileriyle). Numune detayındaki "Parça Tahmini" sekmesi:
  - Önceki numuneye göre anlamlı artan veya uyarı/alarm veren malzemeleri listeler.
  - Kaynak parçaları puanlar. Birden çok malzemenin işaret ettiği parça (ör. Fe + Cr → segman) üst sıraya çıkar.
- **Sınıflandırma:** platform kodu (C9, C10…) → grup (Baykar / TUSAŞ / TEI), yağ tipi, numune tipi (Rodaj / Green / Saha / Sıfır Yağ / Diğer).
- **Sayfalar:**
  - Numuneler: parametre odaklı görünüm
    - Parametre seçici; hazır gruplar: "Uyarı/alarm verenler (otomatik)", "Tüm elementler (spektrometri)", aşınma, kirletici, katkı, fiziksel, FTIR
    - "Yalnız seçili parametrelerde uyarı/alarm olanlar" filtresi
    - Seçili parametrelerin durum renkli değer sütunları; hücrenin üzerine gelince neden görünür
    - En sık uyarı/alarm veren parametreler için tek tık filtre çipleri
  - Trend: tek motor veya filtrelenmiş tüm motorlar. Bir noktanın üzerine gelince motor, numune, tarih, saatler, değer, durum ve neden gösterilir; tüm motorlar görünümünde o motorun çizgisi vurgulanır.
  - İstatistik & Limitler: Excel'e aktarılabilir
  - Malzeme Kaynakları
  - Raporlama: bölümler, kapsam (platform/yağ/numune tipi/motor/tarih aralığı) ve kapak bilgileri seçilir; **PDF** veya **Word (DOCX)** çıktısı alınır, ikisinde de kapak sayfası ve içindekiler bulunur. Seçilebilen bölümler: özet, numune listesi, uyarı/alarm detayları, değerlendirme yorumları, trend grafikleri, parça tahmini, istatistikler, SGS yorumları, hariç tutulan değerler.
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
py -3.8 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-py38.txt
python run.py
```

## Tek dosya .exe oluşturma (Python 3.8)

**`KURULUM_VE_EXE.bat` dosyasına çift tıklayın.** Betik sırasıyla şunları yapar:

1. Python 3.8'i bulur (`py -3.8` veya `python`).
2. Proje klasöründe ayrı bir sanal ortam (`build_env`) oluşturur; sistemdeki Python kurulumuna dokunmaz.
3. Python 3.8 ile test edilmiş sabit sürümlü paketleri kurar (`requirements-py38.txt`, `requirements-build.txt`).
4. PyInstaller ile **tek dosya, konsolsuz** `dist\YagAnalizi.exe` üretir. Tasarım dosyaları ve uygulama ikonu da pakete eklenir.
5. Üretilen exe'yi `--selftest` ile pencere açmadan çalıştırıp doğrular: tema dosyaları, PDF okuma, PDF/Word rapor üretimi, Excel/grafik kütüphaneleri ve tüm sayfalar denenir. Sonuç `build\selftest.txt` dosyasına yazılır.

Tüm çıktı `build\build_log.txt` dosyasına da kaydedilir. Oluşan exe tek başına çalışır; kopyalandığı bilgisayarda Python kurulu olması gerekmez.

Notlar:
- **Python 3.8 başka bir yerdeyse:** `.bat` dosyasındaki `set "PY38=..."` satırına `python.exe` yolunu yazın.
- **Şirket ağında proxy varsa:** Betiği çalıştırmadan önce `set HTTPS_PROXY=http://kullanici:sifre@proxy:port` komutunu verin.
- **Çift tıklamadan çalıştırmak için:** `py -3.8 build_exe.py` komutu aynı işi yapar.
- **Virüs uyarısı:** Bazı antivirüs programları imzasız PyInstaller exe'lerini yanlışlıkla işaretleyebilir; gerekirse BT'den istisna isteyin.

### İnternetsiz bilgisayarda exe oluşturma

1. İnternete bağlı bir Windows bilgisayarda `PAKETLERI_INDIR.bat` dosyasını çalıştırın. Gerekli tüm paketler (yaklaşık 120 MB) `wheels\` klasörüne iner.
2. Proje klasörünü, `wheels\` dahil, internetsiz bilgisayara kopyalayın.
3. `KURULUM_VE_EXE.bat` dosyasını çalıştırın. Betik `wheels\` klasörünü görünce internete çıkmadan oradan kurar.

### Elle (PyInstaller komutu)

```bat
pyinstaller --noconfirm --windowed --onefile --name YagAnalizi ^
  --add-data "oil_analysis/ui/assets;oil_analysis/ui/assets" ^
  --collect-data pdfminer --collect-all pypdfium2 run.py
```

`--add-data` satırı tasarım dosyalarını exe'ye ekler; bu satır olmadan arayüz stilsiz açılır.

## Taranmış PDF'ler için OCR (opsiyonel)

Raporlar normalde metin içerir ve OCR gerekmez. Taranmış bir PDF gelirse:

1. Tesseract programını Türkçe ve İngilizce dil paketleriyle kurun.
2. `pip install pytesseract` komutunu çalıştırın.

Uygulama bu durumda OCR'a otomatik olarak geçer.

## Testler

```bash
pip install pytest "reportlab<4"
python -m pytest tests
```

Testler sentetik SGS düzeninde PDF ve Excel üretip ayrıştırıcıları doğrular. Sentetik PDF'ler şu durumları kapsar:
- Sembol ve Türkçe element adları
- Tek ve çok sütun
- Satır kayması
- Tanınmayan satır
