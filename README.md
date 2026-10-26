# glisweb-agent
agent locale collegato al framework GlisWeb

È la base standard: un deploy che usa l'agent lo usa così com'è, e quello che cambia da un cliente all'altro sta
nel `config.ini`. Un agent personalizzato si deriva da qui solo quando serve qualcosa che il `config.ini` non
esprime.

Il deploy non parla con l'hardware della rete del cliente: è il **browser** che chiama l'agent installato sul PC,
e l'agent inoltra la richiesta al dispositivo. Per i cassetti Modula:

    browser  →  agent sul PC ( 127.0.0.1:5000/modula )  →  cassetto Modula ( socket TCP, [modula] host:porta )

Il server non è nel giro: se il richiamo non funziona, nei log del deploy non c'è niente, a meno che l'agent non
mandi i suoi ( log remoto, sotto ).

## i file

| file | cosa c'è |
|---|---|
| `glisweb-agent.py` | l'agent |
| `config.ini` | il modello della configurazione; **senza il segreto**, che si scrive solo sul PC |
| `icon.png`, `icon.ico` | l'icona vicino all'orologio, letta da `icon.png` nella cartella da cui gira l'agent |
| `.github/workflows/build.yml` | la compilazione dell'exe su Windows |
| `winbuild.bat` | la stessa compilazione, a mano su un PC Windows |
| `glisweb-agent.exe` | la vecchia v1.6, tenuta come storia: gli exe nuovi escono dagli artifact di GitHub Actions |

Lato deploy servono tre pezzi dello standard glisweb: `/api/log` ( `_src/_api/_log.php` ), che riceve i log,
`/api/aggiornamenti` ( `_src/_api/_aggiornamenti.php` ), che distribuisce le versioni nuove, e
`_src/_py/_aggiornamenti.firma.py`, che le firma. Sono documentati nel manuale dello standard.

## come è fatto

È una tray-app Python: un processo con un server Flask in ascolto su `127.0.0.1:5000`, uno con l'icona vicino
all'orologio ( pystray ), notifiche di sistema con plyer. Su Windows si distribuisce come exe compilato con
PyInstaller, su Linux gira come daemon. Accetta tre comandi Modula, nella forma `…|…|<COMANDO>|…`: **CALL**
( richiama un cassetto, e ritenta per cinque minuti finché la piazzola è occupata ), **RETURN** e **STATUS**.

La configurazione è il `config.ini` **nella cartella da cui si lancia l'agent**:

    [modula]
    host = <indirizzo del cassetto>
    porta = <porta del cassetto, di solito 11001>

    [server]
    url = https://<deploy>/api/log
    sorgente = glisweb-agent
    segreto = <il segreto della sorgente>
    host = <nome della postazione, facoltativo: default il nome della macchina>
    battito = <secondi fra un segnale di vita e l'altro: default 3600, 0 lo spegne>
    aggiornamenti = <secondi fra un controllo degli aggiornamenti e l'altro: default 21600, 0 lo spegne>

Senza la sezione `[server]`, o col segreto vuoto, l'agent si comporta come la v1.6: niente log remoto e niente
aggiornamento automatico. Il segreto è quello di `debug.log.remoti.sorgenti.<sorgente>.segreto` nello shadow del
deploy; il valore non va scritto in nessun file versionato.

## diagnosi di un cassetto che non si apre

**Il primo documento è `agent.log`**, accanto all'exe. Per ogni comando dice se è arrivato dal browser, se il
socket verso il cassetto si è connesso e cosa ha risposto il Modula:

| codice | significato |
|---|---|
| `0` | comando eseguito |
| `-1` | CALL: cassetto non valido; RETURN: piazzola vuota |
| `-2` | piazzola non valida |
| `-5` | login non eseguito o piazzola non attiva |
| `-6` | **macchina non in automatico**: il Modula è in manuale dal suo pannello e non accetta comandi da remoto |
| `-99` | l'agent non è riuscito a parlare col cassetto ( rete, indirizzo, Modula spento ) |

Da lì si capisce dove si interrompe la catena:

- **il comando non compare nel log**: il problema sta fra browser e agent. L'agent è avviato ( icona vicino
  all'orologio )? Il browser ha negato il permesso di accedere ai dispositivi della rete locale? Le versioni
  recenti di Chrome lo chiedono prima di lasciare che un sito pubblico chiami `127.0.0.1`, e se è stato negato
  va consentito per il dominio del deploy;
- **il comando c'è, e c'è un errore di connessione o `-99`**: la rete fra il PC e il Modula, o il Modula spento;
- **il comando c'è, e la risposta è `-6`**: il Modula è in manuale.

## log remoto

Con la sezione `[server]` ogni riga di `agent.log` arriva anche sul deploy, in
`var/log/remoti/<nome del PC>/<sorgente>.<livello>.<anno e mese>.log`, con l'ora del PC fra parentesi quadre: si
legge da lì senza chiedere niente al cliente. Un battito ogni ora ( «GlisWeb Agent v… in esecuzione» ) dice che
l'agent è acceso; se il file del mese non cresce da più di un'ora, l'agent è spento o il PC non raggiunge il
deploy. Se la rete manca, le righe aspettano in una coda in memoria ( 5000 al massimo ).

Dalla v1.9 i messaggi viaggiano in **base64** ( `"codifica": "base64"` ). In chiaro, i ritorni a capo delle
tracce d'errore, i `../` e i frammenti di shell o SQL li ferma ModSecurity con un 403. Un 403 dà anche punti
all'IP del PC, e a 10 in un'ora l'IP viene bandito. Per lo stesso motivo un 403 non si riprova: le righe si
scartano, come per 400 e 401.

## compilare l'exe

PyInstaller produce l'eseguibile solo per il sistema su cui gira, e lo compila **GitHub Actions su un runner
Windows** ( `.github/workflows/build.yml` ). Parte da solo a ogni push su `master` che tocca `glisweb-agent.py`,
oppure a mano da *Actions → build → Run workflow*. L'exe si scarica dagli artifact della run
( `glisweb-agent-<versione>` ), insieme a `config.ini` e `icon.png`. La build fallisce se nell'exe manca
`cryptography`, senza la quale l'aggiornamento automatico rifiuterebbe tutto.

Prima di una versione nuova si **alza `versione`** in testa allo script ( p.es. da `'0.1.9'` a `'0.1.10'` ). ⚠ È
la versione che l'agent confronta con quella pubblicata: se il manifest dice `0.1.10` e l'exe dentro dice ancora
`0.1.9`, l'agent riscarica e reinstalla lo stesso file a ogni controllo.

A mano, su un PC Windows: `pip install flask plyer pystray pillow pywin32 pyinstaller cryptography`, poi
`winbuild.bat`; l'exe è in `dist/`.

## installare l'agent la prima volta

L'aggiornamento automatico parte dalla v1.8: da una versione precedente si passa **a mano, una volta sola**,
collegandosi al PC del cliente.

1. chiudere l'agent in esecuzione ( icona vicino all'orologio, *esci* ), e conservarne la cartella così com'è per
   poter tornare indietro;
2. copiare nella stessa cartella l'exe nuovo **col nome che avrà sempre**, p.es. `agent.exe`: gli aggiornamenti
   sostituiscono il file con quel nome, e il riavvio lo cerca lì;
3. completare il `config.ini` con la sezione `[server]` e il segreto;
4. avviare l'exe e controllare: notifica «GlisWeb Agent avviato», poi in `agent.log` le righe *log remoto attivo*
   e *aggiornamento automatico attivo*, e in `var/log/remoti/<nome del PC>/` sul deploy le stesse righe;
5. fare un richiamo di prova, e trovarlo in tutti e due i log;
6. verificare come l'agent parte all'accensione del PC ( esecuzione automatica o cartella *Esecuzione
   automatica* ) e puntarlo all'exe nuovo.

## pubblicare un aggiornamento

Da quando sul PC gira la v1.8 o successiva, una versione nuova si installa da sola: l'agent controlla il deploy
un minuto dopo l'avvio e poi ogni sei ore.

1. compilare l'exe con la versione alzata ( sopra );
2. **firmarlo sul PC dove sta la chiave privata**:
   `python _aggiornamenti.firma.py firma ~/chiavi/glisweb-agent/privata.pem glisweb-agent 0.1.10 glisweb-agent.exe --file agent.exe --uscita pubblica`
   — il `--file` è il nome con cui l'exe è installato sul PC, la versione è quella scritta nello script;
3. controllare: `python _aggiornamenti.firma.py verifica pubblica glisweb-agent <chiave pubblica>`;
4. copiare sul deploy, in `var/spool/aggiornamenti/glisweb-agent/` ( fuori dalla document root servita
   direttamente ), **prima `agent.exe` e poi `manifest.json`**, e dare la cartella a `www-data`;
5. seguire l'installazione nei log remoti: *trovata la v…*, *installata la v… al posto della v…, riavvio*, poi
   *avvio GlisWeb agent v…* e *aggiornamento a v… completato*.

Cosa fa l'agent, in ordine: scarica l'exe accanto al suo come `<exe>.nuovo`, controlla l'hash del manifest e **la
firma Ed25519 con `CHIAVE_PUBBLICA`** scritta nello script, aspetta che non ci siano richiami in corso, rinomina
l'exe in esecuzione in `<exe>.vecchio` e mette il nuovo al suo posto, poi un `cmd` staccato chiude l'agent e
lancia l'exe nuovo nella sua cartella. Partendo, la versione nuova cancella `<exe>.vecchio`. Se la firma non
torna l'aggiornamento si scarta, e nel log c'è **FIRMA NON VALIDA**.

Se l'exe nuovo non partisse, sul PC restano `<exe>.vecchio` e la cartella della versione precedente: si torna
indietro a mano, rinominando `<exe>.vecchio` in `<exe>`. Un ritorno automatico non c'è. ⚠ Il riavvio dopo un
aggiornamento non è ancora stato provato su Windows.

## le chiavi

La firma usa una coppia di chiavi Ed25519, generata il 26/10/2026 con
`python _aggiornamenti.firma.py chiavi ~/chiavi/glisweb-agent`. **È una sola per tutti i deploy**: ogni exe
compilato da qui si fida della stessa chiave.

- **la chiave privata** ( `privata.pem` ) sta **sul PC di chi pubblica, e non va mai su un server né in un
  repository**: è l'unica cosa che impedisce a chi riuscisse a scrivere su un deploy di far installare un suo
  programma sui PC dei clienti. Va tenuta anche in una copia di sicurezza cifrata;
- **la chiave pubblica** è in `CHIAVE_PUBBLICA` in testa a `glisweb-agent.py`, e finisce nell'exe compilato;
- **se la privata si perde** non si possono più firmare aggiornamenti: si genera una coppia nuova, si mette la
  pubblica nuova nello script e l'exe compilato si installa **a mano** una volta su ogni PC, come la prima;
- **se la privata finisce in mani sbagliate** vale lo stesso, e subito, **su tutti i clienti**: finché su un PC
  gira un exe con la pubblica vecchia, chi ha la privata può fargli installare quello che vuole, purché riesca
  anche a scrivere nella cartella dello spool del deploy.

Lo script di firma sta nello standard glisweb ( `_src/_py/_aggiornamenti.firma.py` ) e richiede
`pip install cryptography`: si copia sul PC dove sta la chiave.
