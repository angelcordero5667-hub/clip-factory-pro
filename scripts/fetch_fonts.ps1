# Descarga las fuentes de SUBTÍTULOS que faltan en static/fonts (licencia SIL OFL).
# Ejecutar UNA vez:  powershell -ExecutionPolicy Bypass -File scripts\fetch_fonts.ps1
# Origen: repositorio oficial google/fonts en GitHub. Tamaño total aproximado: 0.5 MB.
#
# Ya incluidas: Sora-Bold, Inter-Regular, JetBrainsMono (interfaz del dashboard).
# Subtítulos del video (libass las usa con fontsdir): Montserrat ExtraBold, Anton, Poppins SemiBold.

$ErrorActionPreference = "Stop"
$dest = Join-Path (Split-Path -Parent $PSScriptRoot) "static\fonts"
New-Item -ItemType Directory -Force $dest | Out-Null
$base = "https://github.com/google/fonts/raw/main/ofl"

$files = @(
    @{ url = "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf/Montserrat-ExtraBold.ttf"; name = "Montserrat-ExtraBold.ttf" },
    @{ url = "$base/anton/Anton-Regular.ttf";                    name = "Anton-Regular.ttf" },
    @{ url = "$base/poppins/Poppins-SemiBold.ttf";               name = "Poppins-SemiBold.ttf" }
)

foreach ($f in $files) {
    $out = Join-Path $dest $f.name
    if (Test-Path $out) { Write-Host "Ya existe: $($f.name)"; continue }
    Write-Host "Descargando $($f.name)..."
    curl.exe -L --fail -o $out $f.url
}
Write-Host "Listo. Los subtítulos usarán estas fuentes en los próximos renders."
