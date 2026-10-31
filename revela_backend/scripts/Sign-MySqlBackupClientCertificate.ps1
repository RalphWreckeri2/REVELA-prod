[CmdletBinding()]
param(
    [string]$OpenSslPath = "openssl.exe"
)

$ErrorActionPreference = "Stop"
$root = Join-Path $env:LOCALAPPDATA "REVELA\DatabaseBackupCA"
$caKeyPath = Join-Path $root "mysql-ca-key.pem"
$caCertPath = Join-Path $root "mysql-ca.pem"
$keyPath = Join-Path $root "backup-client-key.pem"
$csrPath = Join-Path $root "backup-client.csr"
$certPath = Join-Path $root "backup-client-cert.pem"
$extensionPath = Join-Path $root (".backup-client-extensions-" + [Guid]::NewGuid().ToString("N") + ".cnf")
$temporaryPaths = [System.Collections.Generic.List[string]]::new()
$createdOutputs = [System.Collections.Generic.List[string]]::new()
$securePass = $null
$passphrase = $null

function Convert-SecureStringToPlainText([System.Security.SecureString]$Value) {
    $pointer = [IntPtr]::Zero
    try {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
    }
}

function Invoke-OpenSsl([string[]]$Arguments, [string]$Passphrase, [string]$Operation) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $OpenSslPath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "OpenSSL failed to start during $Operation." }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
        if ($null -ne $Passphrase) { $process.StandardInput.WriteLine($Passphrase) }
        $process.StandardInput.Close()
        $process.WaitForExit()
        $null = $stdoutTask.GetAwaiter().GetResult()
        $null = $stderrTask.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) {
            throw "OpenSSL failed during $Operation (exit $($process.ExitCode)); details suppressed."
        }
    }
    finally {
        if (-not $process.HasExited) { $process.Kill() }
        $process.Dispose()
    }
}

function Get-OpenSslText([string[]]$Arguments, [string]$Operation) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $OpenSslPath
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$start.ArgumentList.Add($argument) }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw "OpenSSL failed to start during $Operation." }
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.Close()
    $process.WaitForExit()
    $output = $stdoutTask.GetAwaiter().GetResult()
    $null = $stderrTask.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0) {
        $process.Dispose()
        throw "OpenSSL failed during $Operation (exit $($process.ExitCode)); details suppressed."
    }
    $process.Dispose()
    return $output
}

try {
    $opensslCommand = Get-Command $OpenSslPath -ErrorAction SilentlyContinue
    if (-not $opensslCommand) {
        $gitOpenSsl = "C:\Program Files\Git\usr\bin\openssl.exe"
        if (Test-Path -LiteralPath $gitOpenSsl -PathType Leaf) { $OpenSslPath = $gitOpenSsl }
        $opensslCommand = Get-Command $OpenSslPath -ErrorAction SilentlyContinue
    }
    if (-not $opensslCommand) { throw "OpenSSL is unavailable; no files were changed." }
    $OpenSslPath = $opensslCommand.Source

    foreach ($path in @($caKeyPath, $caCertPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "The existing private CA material is incomplete; no files were changed."
        }
    }
    $folderAcl = Get-Acl -LiteralPath $root
    $currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $allowedSids = @($currentSid, "S-1-5-18", "S-1-5-32-544")
    $aclSids = @($folderAcl.Access | ForEach-Object {
        $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    } | Sort-Object -Unique)
    $ownerSid = $folderAcl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
    $hasUnexpectedAllow = @($aclSids | Where-Object { $_ -notin $allowedSids }).Count -gt 0
    $hasUnexpectedEntry = @($folderAcl.Access | Where-Object {
        $_.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or $_.IsInherited
    }).Count -gt 0
    if ((-not $folderAcl.AreAccessRulesProtected) -or ($ownerSid -ne $currentSid) -or
            ($aclSids.Count -ne $allowedSids.Count) -or $hasUnexpectedAllow -or $hasUnexpectedEntry) {
        throw "The certificate folder ACL is not restricted to its owner, SYSTEM, and local Administrators."
    }

    $outputPaths = @($keyPath, $csrPath, $certPath)
    $existing = @($outputPaths | Where-Object { Test-Path -LiteralPath $_ })
    if ($existing.Count -gt 0) {
        $names = ($existing | ForEach-Object { [System.IO.Path]::GetFileName($_) }) -join ", "
        throw "Client-certificate outputs already exist ($names); refusing to overwrite or regenerate them."
    }

    if ((Get-Content -LiteralPath $caKeyPath -TotalCount 1) -ne "-----BEGIN ENCRYPTED PRIVATE KEY-----") {
        throw "The existing CA key is not encrypted; no client certificate was issued."
    }
    $securePass = Read-Host "Enter the existing private-CA passphrase (input hidden)" -AsSecureString
    $passphrase = Convert-SecureStringToPlainText $securePass
    if ([string]::IsNullOrWhiteSpace($passphrase) -or $passphrase.Contains("`n") -or $passphrase.Contains("`r")) {
        throw "The CA passphrase input was invalid; no client certificate was issued."
    }
    $passphrase = $passphrase.Replace("`r", "").Replace("`n", "")

    Invoke-OpenSsl @("pkey", "-in", $caKeyPath, "-passin", "stdin", "-check", "-noout") $passphrase "CA private-key validation"
    Invoke-OpenSsl @("verify", "-CAfile", $caCertPath, "-check_ss_sig", $caCertPath) $null "CA certificate validation"
    Invoke-OpenSsl @("x509", "-in", $caCertPath, "-checkend", "0", "-noout") $null "CA validity validation"

    $serial = (Get-OpenSslText @("rand", "-hex", "16") "client certificate serial generation").Trim()
    if ($serial -notmatch '^[0-9a-fA-F]{32}$') { throw "OpenSSL returned an invalid serial; no client certificate was issued." }

    Invoke-OpenSsl @(
        "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-out", $keyPath
    ) $null "dedicated client private-key generation"
    $createdOutputs.Add($keyPath)
    Invoke-OpenSsl @(
        "req", "-new", "-key", $keyPath, "-sha256",
        "-subj", "/CN=REVELA-Database-Backup-Client", "-out", $csrPath
    ) $null "client certificate request generation"
    $createdOutputs.Add($csrPath)
    Invoke-OpenSsl @("req", "-in", $csrPath, "-noout", "-verify") $null "client CSR signature validation"

    $extensionText = @"
[client_cert]
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=clientAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
"@
    $extensionStream = [System.IO.File]::Open(
        $extensionPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None
    )
    $temporaryPaths.Add($extensionPath)
    try {
        $extensionBytes = [System.Text.Encoding]::ASCII.GetBytes($extensionText)
        $extensionStream.Write($extensionBytes, 0, $extensionBytes.Length)
    }
    finally { $extensionStream.Dispose() }

    Invoke-OpenSsl @(
        "x509", "-req", "-in", $csrPath, "-CA", $caCertPath, "-CAkey", $caKeyPath,
        "-passin", "stdin", "-set_serial", "0x$serial", "-out", $certPath,
        "-days", "90", "-sha256", "-extfile", $extensionPath, "-extensions", "client_cert"
    ) $passphrase "client certificate signing"
    $createdOutputs.Add($certPath)

    Invoke-OpenSsl @("verify", "-purpose", "sslclient", "-CAfile", $caCertPath, $certPath) $null "client certificate chain and purpose validation"
    Invoke-OpenSsl @("x509", "-in", $certPath, "-checkend", "0", "-noout") $null "client certificate validity validation"
    $eku = Get-OpenSslText @("x509", "-in", $certPath, "-noout", "-ext", "extendedKeyUsage") "clientAuth extension validation"
    if ($eku -notmatch "TLS Web Client Authentication") {
        throw "The certificate does not include clientAuth; outputs were preserved."
    }

    $csrPublic = Get-OpenSslText @("req", "-in", $csrPath, "-pubkey", "-noout") "CSR public-key validation"
    $certPublic = Get-OpenSslText @("x509", "-in", $certPath, "-pubkey", "-noout") "certificate public-key validation"
    if (-not [string]::Equals($csrPublic.Trim(), $certPublic.Trim(), [StringComparison]::Ordinal)) {
        throw "The client certificate does not match its private key; outputs were preserved."
    }

    $identity = Get-OpenSslText @("x509", "-in", $certPath, "-noout", "-subject", "-issuer", "-nameopt", "compat") "certificate identity retrieval"
    Write-Output "Dedicated MySQL client-auth certificate issued and validated."
    Write-Output $identity.Trim()
    Write-Output "Private client key remains in the protected local certificate folder."
    Write-Output "Do not upload the CA signing key or MySQL server private key."
}
catch {
    Write-Error $_.Exception.Message
    if ($createdOutputs.Count -gt 0) {
        Write-Warning "Partial client-certificate outputs were retained; do not rerun or overwrite them."
    }
    exit 1
}
finally {
    if ($null -ne $securePass) { $securePass.Dispose() }
    $passphrase = $null
    foreach ($path in $temporaryPaths) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    }
}
