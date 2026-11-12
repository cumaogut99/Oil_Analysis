@echo off
rem ======================================================================
rem  INTERNETSIZ KURULUM ICIN: internete bagli bir bilgisayarda calistirin.
rem  Gerekli tum paketleri (Windows 64-bit, Python 3.8) "wheels" klasorune
rem  indirir. Sonra proje klasorunu (wheels dahil) internetsiz bilgisayara
rem  kopyalayip KURULUM_VE_EXE.bat dosyasini calistirin.
rem ======================================================================
cd /d "%~dp0"
call "%~dp0KURULUM_VE_EXE.bat" --download-wheels
