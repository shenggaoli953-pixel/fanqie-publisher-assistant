$ErrorActionPreference = 'Stop'

python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m PyInstaller --noconfirm --clean .\FanqiePublisher.spec --distpath .\release --workpath .\build-final
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
