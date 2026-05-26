@echo off
chcp 65001 >nul
echo ============================================================
echo   Invedia BUYMA パイプライン
echo ============================================================
echo.
echo   [1] 候補抽出（ブックマークレット説明）
echo   [2] 候補取込（TSV → シート）
echo   [3] 自動仕入れ検討（intake --auto-sheet）
echo   [4] 対話モード（intake 1件）
echo   [5] 定期監視（main.py）
echo   [6] シート接続確認
echo   [7] コード版チェック
echo   [V] 稼働確認
echo   [Q] 終了
echo.
set /p CHOICE="選択してください: "

if /i "%CHOICE%"=="1" (
    echo ブックマークレットの説明は bookmarklets\README.md を参照してください。
    start "" "bookmarklets\buyma_start.html"
    pause
) else if /i "%CHOICE%"=="2" (
    python scripts\buyma_candidate_import.py
    pause
) else if /i "%CHOICE%"=="3" (
    python -c "from lib.buyma.intake import auto_sheet_mode; auto_sheet_mode()"
    pause
) else if /i "%CHOICE%"=="4" (
    python -c "from lib.buyma.intake import interactive_intake; interactive_intake()"
    pause
) else if /i "%CHOICE%"=="5" (
    python -c "from lib.buyma.main import main; import asyncio; asyncio.run(main())"
    pause
) else if /i "%CHOICE%"=="6" (
    python scripts\buyma_list_sheet_tabs.py
    pause
) else if /i "%CHOICE%"=="7" (
    python scripts\buyma_verify_intake_version.py
    pause
) else if /i "%CHOICE%"=="V" (
    python -c "print('BUYMA pipeline: OK')"
    pause
) else if /i "%CHOICE%"=="Q" (
    exit /b
) else (
    echo 無効な選択です。
    pause
)
