## INSTALLER DEL GLISWEB AGENT
#
# si lancia con installa.bat, dalla cartella dove sono stati estratti glisweb-agent.exe, config.ini e icon.png;
# non chiede di essere amministratore: installa per l'utente corrente in %LOCALAPPDATA%\GlisWebAgent
#
# ogni passo si scrive in installa.log accanto allo script e, se config.ini ha la sezione [server] col segreto,
# anche sul deploy di riferimento ( /api/log, canale installer ): cosi' si sa com'e' andata senza chiederlo al
# cliente; i messaggi viaggiano in base64 come quelli dell'agent, per ModSecurity
#
# il giro: chiude l'agent vecchio, ne mette da parte l'esecuzione automatica, copia i file nella cartella nuova,
# crea il collegamento in Esecuzione automatica, avvia l'agent nuovo e aspetta che risponda su /stato; se qualcosa
# va storto rimette l'agent vecchio com'era, quindi il cliente non resta mai senza agent
#
# NOTA il file resta in ASCII: PowerShell 5.1 legge gli script senza BOM come ANSI, e le lettere accentate si rompono
#

## CONFIGURAZIONE
#

$ErrorActionPreference = 'Stop'

# cartella dello zip estratto e cartella di destinazione
$origine = Split-Path -Parent $MyInvocation.MyCommand.Path
$destinazione = Join-Path $env:LOCALAPPDATA 'GlisWebAgent'
$exe = 'glisweb-agent.exe'
$file = @( $exe, 'config.ini', 'icon.png' )

# collegamento in Esecuzione automatica dell'utente
$avvio = [Environment]::GetFolderPath( 'Startup' )
$collegamento = Join-Path $avvio 'GlisWeb Agent.lnk'

# log locale
$logLocale = Join-Path $origine 'installa.log'

# i deploy rifiutano le connessioni TLS vecchie, che PowerShell 5.1 usa per default
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

## FUNZIONI
#

# lettura del config.ini: una tabella sezione.chiave = valore
function Leggi-Ini( $percorso ) {
    $ini = @{}
    $sezione = ''
    foreach( $riga in Get-Content -Path $percorso ) {
        if( $riga -match '^\s*\[(.+)\]\s*$' ) {
            $sezione = $matches[1].Trim()
        } elseif( $riga -match '^\s*([^;#=][^=]*)=(.*)$' ) {
            $ini[ $sezione + '.' + $matches[1].Trim() ] = $matches[2].Trim()
        }
    }
    return $ini
}

# log di un passo, in locale e se possibile sul deploy
function Scrivi-Log( $livello, $messaggio ) {

    $data = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $riga = "$data ($livello) $messaggio"
    Add-Content -Path $logLocale -Value $riga
    Write-Host $riga

    if( $script:url -and $script:segreto ) {
        try {
            $corpo = @{
                sorgente = $script:sorgente
                host = $script:postazione
                righe = @( @{
                    livello = $livello
                    data = $data
                    canale = 'installer'
                    codifica = 'base64'
                    messaggio = [Convert]::ToBase64String( [Text.Encoding]::UTF8.GetBytes( $messaggio ) )
                } )
            } | ConvertTo-Json -Depth 4
            Invoke-RestMethod -Uri $script:url -Method Post -ContentType 'application/json' -Headers @{ gliswebLogKey = $script:segreto } -Body ( [Text.Encoding]::UTF8.GetBytes( $corpo ) ) -TimeoutSec 10 | Out-Null
        } catch {
            Add-Content -Path $logLocale -Value "$data (warning) log remoto non raggiungibile: $_"
        }
    }

}

# agent in esecuzione: il v1.6 si chiama agent16.exe, dal v1.10 glisweb-agent.exe; il nome con le cifre e' voluto,
# un 'agent.exe' qualsiasi puo' essere il programma di qualcun altro
function Trova-Agent {
    return @( Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(agent\d+|glisweb-agent)$' -and $_.Path } )
}

# risposta dell'agent su /stato, o $null
function Chiedi-Stato {
    try {
        return Invoke-RestMethod -Uri 'http://127.0.0.1:5000/stato' -TimeoutSec 3
    } catch {
        return $null
    }
}

# ripristino dell'agent vecchio: toglie il nuovo e rimette l'esecuzione automatica e il processo di prima
function Ripristina( $passo ) {

    Scrivi-Log 'err' "installazione fallita al passo: $passo; ripristino l'agent precedente"

    try {
        Trova-Agent | Where-Object { $_.Path -like "$destinazione\*" } | Stop-Process -Force -ErrorAction SilentlyContinue
        if( Test-Path $collegamento ) { Remove-Item $collegamento -Force }
        foreach( $c in $script:collegamentiVecchi ) {
            Move-Item -Path $c.Copia -Destination $c.Originale -Force
            Scrivi-Log 'info' "rimesso il collegamento $( $c.Originale )"
        }
        foreach( $r in $script:runVecchi ) {
            Set-ItemProperty -Path $r.Chiave -Name $r.Nome -Value $r.Valore
            Scrivi-Log 'info' "rimessa la voce $( $r.Nome ) in $( $r.Chiave )"
        }
        if( $script:vecchioExe ) {
            Start-Process -FilePath $script:vecchioExe -WorkingDirectory ( Split-Path -Parent $script:vecchioExe )
            Scrivi-Log 'notice' "riavviato l'agent precedente $script:vecchioExe"
        }
    } catch {
        Scrivi-Log 'crit' "ripristino non riuscito: $_; l'agent precedente va rimesso a mano"
    }

    Scrivi-Log 'err' 'installazione NON riuscita'
    exit 1

}

## CONTROLLI
#

# config.ini prima di tutto: dice dove mandare il log
$script:url = $null
$script:segreto = $null
$script:sorgente = 'glisweb-agent'
$script:postazione = $env:COMPUTERNAME
$script:collegamentiVecchi = @()
$script:runVecchi = @()
$script:vecchioExe = $null

$configIni = Join-Path $origine 'config.ini'
if( Test-Path $configIni ) {
    $ini = Leggi-Ini $configIni
    $script:url = $ini['server.url']
    $script:segreto = $ini['server.segreto']
    if( $ini['server.sorgente'] ) { $script:sorgente = $ini['server.sorgente'] }
    if( $ini['server.host'] ) { $script:postazione = $ini['server.host'] }
}

Scrivi-Log 'notice' "installazione avviata da $env:USERNAME su $env:COMPUTERNAME, da $origine verso $destinazione"

if( -not $script:segreto ) {
    Scrivi-Log 'warning' 'config.ini senza segreto in [server]: questa installazione si logga solo in installa.log'
}

# i file da installare ci sono tutti? se manca l'exe, di solito l'ha messo in quarantena l'antivirus all'estrazione
foreach( $f in $file ) {
    if( -not ( Test-Path ( Join-Path $origine $f ) ) ) {
        Scrivi-Log 'err' "manca $f nella cartella dell'installer: lo zip va estratto tutto prima di lanciare installa.bat ( se manca solo l'exe, controllare la quarantena dell'antivirus )"
        Scrivi-Log 'err' 'installazione NON riuscita'
        exit 1
    }
}

## INSTALLAZIONE
#

# 1. chiusura dell'agent in esecuzione
$inEsecuzione = Trova-Agent
if( $inEsecuzione.Count -gt 0 ) {
    $vecchi = @( $inEsecuzione | Where-Object { $_.Path -notlike "$destinazione\*" } )
    if( $vecchi.Count -gt 0 ) { $script:vecchioExe = $vecchi[0].Path }
    Scrivi-Log 'info' "agent in esecuzione: $( ( $inEsecuzione | ForEach-Object { $_.Path } | Sort-Object -Unique ) -join ', ' )"
    try {
        $inEsecuzione | Stop-Process -Force
        Start-Sleep -Seconds 3
    } catch {
        Ripristina "chiusura dell'agent in esecuzione ( $_ )"
    }
} else {
    Scrivi-Log 'warning' 'nessun agent in esecuzione'
}

# 2. esecuzione automatica dell'agent vecchio, messa da parte per poterla rimettere
try {
    $parcheggio = Join-Path $destinazione 'avvio-precedente'
    $shell = New-Object -ComObject WScript.Shell
    foreach( $cartella in @( $avvio, [Environment]::GetFolderPath( 'CommonStartup' ) ) ) {
        foreach( $lnk in @( Get-ChildItem -Path $cartella -Filter '*.lnk' -ErrorAction SilentlyContinue ) ) {
            $obiettivo = $shell.CreateShortcut( $lnk.FullName ).TargetPath
            if( $lnk.FullName -ne $collegamento -and $obiettivo -match '\\(agent\d+|glisweb-agent)\.exe$' ) {
                New-Item -ItemType Directory -Path $parcheggio -Force | Out-Null
                $copia = Join-Path $parcheggio $lnk.Name
                Move-Item -Path $lnk.FullName -Destination $copia -Force
                $script:collegamentiVecchi += @{ Originale = $lnk.FullName; Copia = $copia }
                Scrivi-Log 'info' "messo da parte il collegamento $( $lnk.FullName ) -> $obiettivo"
            }
        }
    }
    foreach( $chiave in @( 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run', 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run' ) ) {
        $voci = Get-ItemProperty -Path $chiave -ErrorAction SilentlyContinue
        if( $voci ) {
            foreach( $p in $voci.PSObject.Properties ) {
                if( $p.Name -notlike 'PS*' -and "$( $p.Value )" -match '\\(agent\d+|glisweb-agent)\.exe' ) {
                    Remove-ItemProperty -Path $chiave -Name $p.Name
                    $script:runVecchi += @{ Chiave = $chiave; Nome = $p.Name; Valore = $p.Value }
                    Scrivi-Log 'info' "tolta la voce $( $p.Name ) da $chiave ( $( $p.Value ) )"
                }
            }
        }
    }
    foreach( $t in @( Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { ( $_.Actions | ForEach-Object { $_.Execute } ) -match '(agent\d+|glisweb-agent)\.exe' } ) ) {
        Scrivi-Log 'warning' "operazione pianificata che avvia un agent, NON toccata: $( $t.TaskPath )$( $t.TaskName )"
    }
    if( $script:collegamentiVecchi.Count -eq 0 -and $script:runVecchi.Count -eq 0 ) {
        Scrivi-Log 'warning' "nessuna esecuzione automatica dell'agent precedente trovata"
    }
} catch {
    Ripristina "esecuzione automatica dell'agent precedente ( $_ )"
}

# 3. copia dei file, e controllo che l'antivirus non si sia preso l'exe
try {
    New-Item -ItemType Directory -Path $destinazione -Force | Out-Null
    foreach( $f in $file ) {
        Copy-Item -Path ( Join-Path $origine $f ) -Destination ( Join-Path $destinazione $f ) -Force
        Unblock-File -Path ( Join-Path $destinazione $f )
    }
    Start-Sleep -Seconds 5
    if( -not ( Test-Path ( Join-Path $destinazione $exe ) ) ) {
        throw "l'exe e' sparito dopo la copia, probabilmente in quarantena dell'antivirus"
    }
    Scrivi-Log 'info' "file copiati in $destinazione"
} catch {
    Ripristina "copia dei file ( $_ )"
}

# 4. esecuzione automatica dell'agent nuovo
try {
    $nuovo = $shell.CreateShortcut( $collegamento )
    $nuovo.TargetPath = Join-Path $destinazione $exe
    $nuovo.WorkingDirectory = $destinazione
    $nuovo.Description = 'GlisWeb Agent'
    $nuovo.Save()
    Scrivi-Log 'info' "creato il collegamento $collegamento"
} catch {
    Ripristina "collegamento in Esecuzione automatica ( $_ )"
}

# 5. avvio, nella sua cartella perche' legge config.ini e icon.png da li', e attesa della risposta su /stato
try {
    Start-Process -FilePath ( Join-Path $destinazione $exe ) -WorkingDirectory $destinazione
} catch {
    Ripristina "avvio dell'agent ( $_ )"
}

$stato = $null
for( $i = 0; $i -lt 30 -and -not $stato; $i++ ) {
    Start-Sleep -Seconds 2
    $stato = Chiedi-Stato
}

if( -not $stato ) {
    Ripristina "l'agent non risponde su http://127.0.0.1:5000/stato dopo un minuto"
}

Scrivi-Log 'notice' "installazione riuscita: GlisWeb Agent v$( $stato.versione ) in esecuzione ( PID $( $stato.pid ) ) da $destinazione"
exit 0
