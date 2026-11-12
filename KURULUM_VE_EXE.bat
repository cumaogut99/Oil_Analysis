@echo off
rem ======================================================================
rem  Motor Yagi Analiz - kurulum ve tek dosya EXE olusturma
rem  Cift tiklayin. Python 3.8 bulunur, build_env sanal ortami kurulur,
rem  paketler yuklenir ve dist\YagAnalizi.exe olusturulur.
rem
rem  Python 3.8 farkli bir yerdeyse once su satiri acip yolu yazin:
rem  set "PY38=C:\Python38\python.exe"
rem
rem  Sirket aginda proxy gerekiyorsa:
rem  set "HTTPS_PROXY=http://kullanici:sifre@proxy:port"
rem ======================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if defined PY38 goto check_custom

py -3.8 -c "import sys" >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYCMD=py -3.8"
    goto run
)

python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,8) else 1)" >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYCMD=python"
    goto run
)

echo.
echo [HATA] Python 3.8 bulunamadi.
echo  - Python 3.8 kurun (python.org, "py launcher" secenegi isaretli olsun), veya
echo  - bu dosyayi duzenleyip PY38 satirina python.exe yolunu yazin.
echo.
pause
exit /b 1

:check_custom
if not exist "%PY38%" (
    echo [HATA] PY38 yolu bulunamadi: %PY38%
    pause
    exit /b 1
)
set "PYCMD="%PY38%""

:run
echo Kullanilan Python: %PYCMD%
%PYCMD% build_exe.py %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" goto failed
if "%~1"=="--download-wheels" goto downloaded
echo [TAMAM] Exe hazir: "%~dp0dist\YagAnalizi.exe"
goto end
:downloaded
echo [TAMAM] Paketler "%~dp0wheels" klasorune indirildi.
goto end
:failed
echo [HATA] Islem tamamlanamadi. Ayrinti: "%~dp0build\build_log.txt"
:end
echo.
pause
exit /b %RC%
