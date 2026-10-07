[CmdletBinding()]
param(
    [ValidatePattern('^\d+\.\d+\.\d+(\.\d+)?$')]
    [string]$Version = '2.0.0',
    [switch]$SkipDependencyInstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot 'venv\Scripts\python.exe'
$requirements = Join-Path $projectRoot 'requirements.txt'
$specFile = Join-Path $projectRoot 'specs\RDC_STAMPER_V2_INSTALLER.spec'
$issFile = Join-Path $PSScriptRoot 'RDC_Stamper_V2.iss'
$distDir = Join-Path $projectRoot 'dist\RDC_STAMPER_V2'
$outputDir = Join-Path $projectRoot 'installer-output'
$installerFile = Join-Path $outputDir "RDC_Stamper_V2_Setup_${Version}_x64.exe"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Find-InnoCompiler {
    $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

Push-Location $projectRoot
try {
    Write-Host "Building RDC Stamper V2 $Version installer..."

    if (-not (Test-Path -LiteralPath $venvPython)) {
        $systemPython = (Get-Command 'python.exe' -ErrorAction Stop).Source
        Invoke-Checked $systemPython '-m' 'venv' (Join-Path $projectRoot 'venv')
    }

    if (-not $SkipDependencyInstall) {
        Invoke-Checked $venvPython '-m' 'pip' 'install' '--disable-pip-version-check' '-r' $requirements
    }

    Invoke-Checked $venvPython '-m' 'PyInstaller' '--noconfirm' '--clean' $specFile

    $requiredRuntimeFiles = @(
        (Join-Path $distDir 'RDC_STAMPER_V2.exe'),
        (Join-Path $distDir '_internal\app_icon.ico'),
        (Join-Path $distDir '_internal\tesseract\tesseract.exe'),
        (Join-Path $distDir '_internal\tesseract\tessdata\eng.traineddata')
    )
    foreach ($requiredFile in $requiredRuntimeFiles) {
        if (-not (Test-Path -LiteralPath $requiredFile)) {
            throw "Self-contained runtime validation failed; missing: $requiredFile"
        }
    }

    $iscc = Find-InnoCompiler
    if (-not $iscc) {
        throw "Inno Setup 6 was not found. Install it with: winget install --id JRSoftware.InnoSetup --exact"
    }

    Invoke-Checked $iscc "/DMyAppVersion=$Version" $issFile

    if (-not (Test-Path -LiteralPath $installerFile)) {
        throw "Installer compilation completed but the expected output was not found: $installerFile"
    }

    $installer = Get-Item -LiteralPath $installerFile
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $installerFile
    Write-Host ''
    Write-Host 'Installer build completed successfully.'
    Write-Host "Path:   $($installer.FullName)"
    Write-Host ("Size:   {0:N1} MB" -f ($installer.Length / 1MB))
    Write-Host "SHA256: $($hash.Hash)"
}
finally {
    Pop-Location
}
