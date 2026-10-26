#!/usr/bin/python3

## NOTE
#
# l'exe lo compila GitHub Actions su Windows ( .github/workflows/build.yml ); in locale, su Windows:
# python.exe -m PyInstaller --onefile --noconsole --hidden-import plyer.platforms.win.notification -w glisweb-agent.py
#
# dalla v1.7 l'agent manda le righe di agent.log anche al deploy di riferimento, su /api/log ( _src/_api/_log.php
# del framework ), se config.ini ha la sezione [server]:
#
# [server]
# url = https://<deploy>/api/log
# sorgente = glisweb-agent
# segreto = <il segreto di debug.log.remoti.sorgenti.glisweb-agent nello shadow del deploy>
# host = <nome della postazione, facoltativo: default il nome della macchina>
# battito = <secondi fra un segnale di vita e l'altro, facoltativo: default 3600, 0 per spegnerlo>
# aggiornamenti = <secondi fra un controllo degli aggiornamenti e l'altro, facoltativo: default 21600, 0 per spegnerlo>
#
# dalla v1.8 l'agent si aggiorna da solo da /api/aggiornamenti ( _src/_api/_aggiornamenti.php del framework ), con
# la stessa sorgente e lo stesso segreto del log remoto: scarica l'exe pubblicato in var/spool/aggiornamenti/<sorgente>/
# del deploy e lo installa SOLO se la firma Ed25519 torna con CHIAVE_PUBBLICA qui sotto. L'exe si firma con
# _src/_py/_aggiornamenti.firma.py e la chiave privata, che sta sul PC di chi pubblica e mai sul server. Con
# CHIAVE_PUBBLICA vuota, fuori da Windows o lanciato come script l'aggiornamento automatico e' spento
#
# dalla v1.9 i messaggi del log remoto viaggiano in base64 ( "codifica": "base64" ): in chiaro, i ritorni a capo
# delle tracce d'errore, i ../ e i frammenti di shell o SQL li ferma ModSecurity con un 403, che da' anche punti
# all'IP del PC fino al bando
#
# senza la sezione [server] l'agent si comporta come la v1.6; il segreto NON va nel config.ini versionato
#
# pip install flask plyer pystray pillow pywin32 pyinstaller cryptography ( su Windows )
# pip install flask plyer pystray pillow python-daemon cryptography ( su Linux )
#
# https://support.microsoft.com/en-us/windows/add-an-exclusion-to-windows-security-811816c0-4dfd-af4a-47e4-c301afe13b26
# https://developer.microsoft.com/en-us/windows/downloads/virtual-machines/
#

## IMPORTAZIONE LIBRERIE
#

import os
import sys
import logging
import platform
import time
import socket
import configparser
import json
import threading
import collections
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import base64
import subprocess

import pystray
from pystray import MenuItem, Icon
from PIL import Image
from plyer import notification

from flask import Flask, request, jsonify

import multiprocessing
from multiprocessing import Process, Queue

# trovo il sistema operativo
system = platform.system()

# inclusioni specifiche per il sistema operativo
if system == "Linux":
    from daemon import DaemonContext
elif system == "Windows":
    import subprocess
    import ctypes

## CONFIGURAZIONE GENERALE
#

# numero di versione
versione = '0.1.9'

# chiave pubblica Ed25519 degli aggiornamenti, in base64 ( la stampa _aggiornamenti.firma.py chiavi ); vuota = spento
CHIAVE_PUBBLICA = 'eI6AoDHdrfEnqm4N48ie41GcmsvQk5xYZoNplokF9bI='

# lettura del file di configurazione
config = configparser.ConfigParser()
config.read_file( open( 'config.ini' ) )

# formato del log
logformat = '%(asctime)s [%(levelname)s] %(filename)s: %(message)s'

# configurazione del logger
logger = logging.getLogger(__name__)
logging.basicConfig(filename='agent.log', encoding='utf-8', format=logformat, level=logging.DEBUG)

## LOG REMOTO
#

# handler che manda le righe del log al deploy di riferimento
class RemoteHandler( logging.Handler ):

    # nomi dei livelli di logging nei nomi dei livelli syslog che si aspetta il deploy
    livelli = { logging.CRITICAL: 'crit', logging.ERROR: 'err', logging.WARNING: 'warning', logging.INFO: 'info', logging.DEBUG: 'debug' }

    def __init__( self, url, sorgente, segreto, host ):

        logging.Handler.__init__( self )

        self.url = url
        self.sorgente = sorgente
        self.segreto = segreto
        self.host = host

        # coda in memoria: se la rete manca le righe aspettano qui; oltre il limite si scartano le nuove e si
        # contano, perche' togliere le vecchie sposterebbe quelle che il thread sta mandando
        self.coda = collections.deque()
        self.limite = 5000
        self.perse = 0
        self.evento = threading.Event()

        # NOTA gli errori di invio vanno solo in agent.log, con un logger che non passa da questo handler
        self.locale = logging.getLogger( 'remoto' )
        self.raggiungibile = True

        # il thread si avvia al primo uso, nel processo che scrive: il server e l'icona sono processi diversi
        self.thread = None

    def emit( self, record ):

        try:

            if len( self.coda ) >= self.limite:
                self.perse += 1
                return

            self.coda.append( {
                'livello': self.livelli.get( record.levelno, 'debug' ),
                'data': time.strftime( '%Y-%m-%d %H:%M:%S', time.localtime( record.created ) ),
                'codifica': 'base64',
                'messaggio': base64.b64encode( f'[{ record.processName }] { record.getMessage() }'.encode( 'utf-8' ) ).decode( 'ascii' )
            } )

            if self.thread is None or self.thread.ident is None or not self.thread.is_alive():
                self.thread = threading.Thread( target=self.invia, name='log_remoto', daemon=True )
                self.thread.start()

            self.evento.set()

        except Exception:
            self.handleError( record )

    def invia( self ):

        while True:

            # aspetto una riga nuova, o al massimo un minuto per riprovare quelle rimaste
            self.evento.wait( 60 )
            self.evento.clear()

            # raccolgo un po' di righe insieme
            time.sleep( 2 )

            while self.coda:

                # al massimo cento righe per richiesta, come accetta il deploy
                righe = [ self.coda[ i ] for i in range( min( 100, len( self.coda ) ) ) ]

                try:

                    richiesta = urllib.request.Request(
                        self.url,
                        data=json.dumps( { 'sorgente': self.sorgente, 'host': self.host, 'righe': righe } ).encode( 'utf-8' ),
                        headers={ 'Content-Type': 'application/json', 'gliswebLogKey': self.segreto },
                        method='POST'
                    )

                    with urllib.request.urlopen( richiesta, timeout=10 ) as risposta:
                        risposta.read()

                    # tolgo dalla coda le righe consegnate
                    for i in range( len( righe ) ):
                        self.coda.popleft()

                    if not self.raggiungibile:
                        self.locale.info( f'log remoto di nuovo raggiungibile ( {self.url} ), righe in coda: {len(self.coda)}, perse per coda piena: {self.perse}' )
                        self.raggiungibile = True
                        self.perse = 0

                except urllib.error.HTTPError as e:

                    # il deploy ha risposto ma rifiuta: con 400 e 401 riprovare non serve, le righe si scartano; il 403
                    # e' ModSecurity, e riprovare darebbe altri punti all'IP del PC fino al bando
                    if e.code in ( 400, 401, 403 ):
                        self.locale.error( f'log remoto rifiutato dal deploy ( HTTP {e.code} ), scartate {len(righe)} righe' )
                        for i in range( len( righe ) ):
                            self.coda.popleft()
                    else:
                        self.segnala( f'HTTP {e.code}' )
                        break

                except Exception as e:

                    # rete assente o deploy irraggiungibile: le righe restano in coda per il giro dopo
                    self.segnala( e )
                    break

    def segnala( self, errore ):

        # lo stato si scrive in agent.log solo quando cambia, per non riempirlo a ogni tentativo
        if self.raggiungibile:
            self.locale.warning( f'log remoto non raggiungibile ( {self.url} ): {errore}; le righe restano in coda' )
            self.raggiungibile = False

# attivazione del log remoto, se configurato
remoto = None
if config.has_section( 'server' ) and config.get( 'server', 'url', fallback='' ) and config.get( 'server', 'segreto', fallback='' ):
    remoto = RemoteHandler(
        config.get( 'server', 'url' ),
        config.get( 'server', 'sorgente', fallback='glisweb-agent' ),
        config.get( 'server', 'segreto' ),
        config.get( 'server', 'host', fallback='' ) or socket.gethostname()
    )
    logger.addHandler( remoto )

# log
logger.info(f'avvio GlisWeb agent v{versione} su {system}')
if remoto is not None:
    logger.info(f'log remoto attivo verso {remoto.url} come {remoto.sorgente}@{remoto.host}')
else:
    logger.info('log remoto non configurato, scrivo solo in agent.log')

# pulizia dell'exe sostituito dall'ultimo aggiornamento: se questo processo parte, il nuovo funziona
if getattr( sys, 'frozen', False ) and os.path.exists( sys.executable + '.vecchio' ):
    try:
        os.remove( sys.executable + '.vecchio' )
        logger.info(f'aggiornamento a v{versione} completato, rimosso {sys.executable}.vecchio')
    except Exception:
        pass

# coda di comunicazione tra i processi
messaggi = Queue()

# lista dei processi
processi = []

## FUNZIONI DI SUPPORTO PER I COMANDI MODULA
#

# funzione per il parsing dei comandi Modula
def parse_modula( comando ):

    # esplodo il comando per | e ritorno un array
    cmdinfo = comando.split('|')

    # eseguo il trim di ogni elemento dell'array
    cmdinfo = [ x.strip() for x in cmdinfo ]

    return cmdinfo

# funzione per l'invio dei comandi Modula
def send_command( comando ):

    logger.info(F'invio del comando: {comando}')

    host = config["modula"]["host"]
    porta = int(config["modula"]["porta"])
    buf_size = 30

    try:

        logger.info('creazione socket...')
        s = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        logger.info('socket creato con successo')

        logger.info(f'connessione alla porta {porta}')
        s.connect((host,porta))
        logger.info(f'socket connesso correttamente alla porta {porta}')

        logger.info(f'codifico in UTF-8 il comando {comando}')
        msg = comando.encode('utf-8') + b'\r'

        logger.info(f'invio i dati al server {host}:{porta}')
        s.send(msg)
        logger.info(f'comando {comando} inviato correttamente al server {host}:{porta}')

        logger.info('ricevo i dati dal server...')
        data = s.recv(buf_size)

        logger.info('decodifico i dati rivevuti...')
        data = data.decode('utf-8')

        logger.info(f'risposta ricevuta dal server: { data }')

        logger.info('disconnetto il socket...')
        s.close()
        logger.info('socket disconnesso con successo')

    except Exception as e:
            logger.error(f'errore durante l\'invio del comando: { e }')
            data = '-99'

    return parse_modula(data)

# funzione per l'invio pigro dei comandi
def lazy_call(comando):
    logger.info(f'invio pigro del comando CALL: {comando}')

    # TODO gli altri processi dovrebbero avere contezza dei comandi in coda e del numero di tentativi rimanenti

    tentativi = 0

    while True:
        time.sleep(1)
        tentativi += 1

        data = send_command(comando)

        # se data è una lista e ha almeno 4 elementi
        if isinstance(data, list) and len(data) >= 4:
            if data[3] == '0':
                logger.info('comando CALL eseguito con successo, esco dal ciclo...')
                break
            elif data[3] == '-1':
                logger.info('cassetto non valido, esco dal ciclo...')
                break
            elif data[3] == '-2':
                logger.info('piazzola non valida, esco dal ciclo...')
                break
            elif data[3] == '-5':
                logger.info('login non eseguito o piazzola non attiva, esco dal ciclo...')
                break
            elif data[3] == '-6':
                logger.info('macchina non in automatico, esco dal ciclo...')
                break
            elif tentativi >= 300:
                logger.info(f'raggiunto il limite di tentativi ({tentativi}) per il comando {comando}, esco dal ciclo...')
                notification.notify( title='GlisWeb Agent', message=f'comando {comando} scartato per timeout', timeout=5 )
                break
            else:
                logger.info(f'comando CALL non eseguito ({data[3]}), continuo il ciclo...')
        else:
            logger.error(f'errore durante l\'invio del comando CALL: {data}')
            break

    return data

## FUNZIONI DI SUPPORTO PER L'ICONA DI SISTEMA
#

# funzione per mostrare la finestra di informazioni
def show_info(icon):

    # log
    logger.info('mostrata la finestra di informazioni')

    # messaggio
    messaggio = f'GlisWeb Agent v{versione} in esecuzione su {system} (PID: {os.getpid()}) \n\n'
    for processo in processi:
        messaggio += f'Processo: {processo.name} (PID: {processo.pid}) \n'

    # notifica di sistema
    if system == "Linux":
        notification.notify( title='GlisWeb Agent', message=messaggio, timeout=5 )
    elif system == "Windows":
        icon.notify('GlisWeb Agent', messaggio)
    else:
        logger.error(f'sistema operativo non supportato: {system}')

# funzione per l'uscita dal programma
def graceful_exit(icon):

    # log
    logger.info('uscita dal programma')

    # notifica di sistema
    notification.notify( title='GlisWeb Agent', message='Chiusura in corso...', timeout=5 )

    # chiusura dei processi
    for processo in processi:
        logger.info(f'terminazione del processo {processo.name} (PID: {processo.pid})')
        processo.terminate()

    # uscita dal programma
    icon.stop()

## FUNZIONI PER I PROCESSI PRINCIPALI
#

# funzione per il segnale di vita verso il log remoto
def heartbeat():

    # intervallo in secondi, 0 per spegnerlo
    battito = config.getint( 'server', 'battito', fallback=3600 )

    while battito > 0:
        time.sleep( battito )
        logger.info(f'GlisWeb Agent v{versione} in esecuzione (PID: {os.getpid()}), cassetto {config["modula"]["host"]}:{config["modula"]["porta"]}')

## AGGIORNAMENTO AUTOMATICO
#

# comandi Modula in corso nel processo server: l'aggiornamento aspetta che siano zero
comandi_in_corso = 0
comandi_lock = threading.Lock()

# funzione per il confronto delle versioni, p.es. '0.1.10' piu' nuova di '0.1.9'
def version_tuple( v ):
    return tuple( int( x ) for x in str( v ).split( '.' ) )

# funzione per la verifica della firma di un aggiornamento
def verify_update( sorgente, nuova, sha256, firma ):

    # NOTA importata qui perche' senza aggiornamento automatico cryptography non serve
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        chiave = Ed25519PublicKey.from_public_bytes( base64.b64decode( CHIAVE_PUBBLICA ) )
        chiave.verify( base64.b64decode( firma ), f'{sorgente}\n{nuova}\n{sha256}'.encode( 'utf-8' ) )
        return True
    except Exception:
        return False

# funzione per la richiesta al deploy, col segreto della sorgente
def update_request( url ):
    return urllib.request.Request( url, headers={ 'gliswebLogKey': config.get( 'server', 'segreto' ) }, method='GET' )

# funzione per il controllo e l'installazione di un aggiornamento
def check_update():

    sorgente = config.get( 'server', 'sorgente', fallback='glisweb-agent' )
    base = config.get( 'server', 'aggiornamenti_url', fallback='' ) or config.get( 'server', 'url' ).rsplit( '/', 1 )[0] + '/aggiornamenti'
    base += '?sorgente=' + urllib.parse.quote( sorgente )

    # manifest
    try:
        with urllib.request.urlopen( update_request( base ), timeout=30 ) as risposta:
            manifest = json.loads( risposta.read().decode( 'utf-8' ) )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug('nessun aggiornamento pubblicato')
            return
        raise

    if version_tuple( manifest['versione'] ) <= version_tuple( versione ):
        logger.debug(f'nessun aggiornamento: pubblicata v{manifest["versione"]}, in esecuzione v{versione}')
        return

    logger.info(f'trovata la v{manifest["versione"]} ( in esecuzione v{versione} ), scarico...')

    # scaricamento accanto all'exe, calcolando l'hash mentre si scrive
    eseguibile = sys.executable
    nuovo = eseguibile + '.nuovo'
    impronta = hashlib.sha256()
    with urllib.request.urlopen( update_request( base + '&scarica=1' ), timeout=120 ) as risposta, open( nuovo, 'wb' ) as f:
        while True:
            blocco = risposta.read( 65536 )
            if not blocco:
                break
            impronta.update( blocco )
            f.write( blocco )

    # il file deve essere quello dichiarato, e firmato da noi
    if impronta.hexdigest() != manifest['sha256']:
        os.remove( nuovo )
        logger.error(f'aggiornamento v{manifest["versione"]} scartato: il file scaricato non corrisponde all\'hash')
        return

    if not verify_update( sorgente, manifest['versione'], manifest['sha256'], manifest['firma'] ):
        os.remove( nuovo )
        logger.error(f'aggiornamento v{manifest["versione"]} scartato: FIRMA NON VALIDA, il file non viene installato')
        return

    # mai a meta' di un richiamo del cassetto: si aspetta al massimo dieci minuti, poi si riprova al giro dopo
    for i in range( 120 ):
        with comandi_lock:
            if comandi_in_corso == 0:
                break
        time.sleep( 5 )
    else:
        os.remove( nuovo )
        logger.warning(f'aggiornamento v{manifest["versione"]} rimandato: comandi Modula in corso da dieci minuti')
        return

    # sostituzione: Windows permette di rinominare l'exe in esecuzione, non di sovrascriverlo
    vecchio = eseguibile + '.vecchio'
    if os.path.exists( vecchio ):
        os.remove( vecchio )
    os.rename( eseguibile, vecchio )
    try:
        os.rename( nuovo, eseguibile )
    except Exception:
        os.rename( vecchio, eseguibile )
        raise

    logger.warning(f'installata la v{manifest["versione"]} al posto della v{versione}, riavvio')

    # tempo al log remoto per consegnare le ultime righe
    time.sleep( 5 )

    # riavvio: un cmd staccato chiude tutti i processi dell'agent e lancia l'exe nuovo nella sua cartella, dove sta config.ini
    nome = os.path.basename( eseguibile )
    cartella = os.path.dirname( eseguibile )
    subprocess.Popen(
        f'ping -n 4 127.0.0.1 >nul & taskkill /F /IM "{nome}" >nul & ping -n 3 127.0.0.1 >nul & start "" /D "{cartella}" "{eseguibile}"',
        shell=True, close_fds=True, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    )

# funzione per il controllo periodico degli aggiornamenti
def updater():

    # intervallo in secondi, 0 per spegnerlo
    intervallo = config.getint( 'server', 'aggiornamenti', fallback=21600 )

    # il primo controllo dopo un minuto, ad avvio finito
    time.sleep( 60 )

    while intervallo > 0:
        try:
            check_update()
        except Exception as e:
            logger.warning(f'controllo degli aggiornamenti non riuscito: {e}')
        time.sleep( intervallo )

# funzione per l'avvio del server Flask
def run_server():

    # log
    logger.info('avviato il server Flask (PID: %d)' % os.getpid())

    # segnale di vita, solo se c'e' il log remoto
    if remoto is not None:
        threading.Thread( target=heartbeat, name='heartbeat', daemon=True ).start()

    # aggiornamento automatico, solo per l'exe su Windows con log remoto e chiave pubblica
    if remoto is None or not CHIAVE_PUBBLICA:
        logger.info('aggiornamento automatico spento: manca il log remoto o la chiave pubblica')
    elif not getattr( sys, 'frozen', False ) or system != 'Windows':
        logger.info('aggiornamento automatico spento: funziona solo per l\'exe su Windows')
    else:
        logger.info('aggiornamento automatico attivo')
        threading.Thread( target=updater, name='updater', daemon=True ).start()

    # avvio del server Flask
    app = Flask(__name__)

    # conteggio dei comandi in corso, per non aggiornare a meta' di un richiamo
    @app.before_request
    def before_request():
        global comandi_in_corso
        with comandi_lock:
            comandi_in_corso += 1

    @app.teardown_request
    def teardown_request(errore):
        global comandi_in_corso
        with comandi_lock:
            comandi_in_corso -= 1

    # route per il preflight CORS
    @app.after_request
    def after_request(risposta):

        # log
        logger.info('richiesta CORS')

        # header HTTP da restituire
        risposta.headers.add('Access-Control-Allow-Origin', '*')
        risposta.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        risposta.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

        # restituisco la risposta
        return risposta

    # route per la ricezione dei comandi Modula
    @app.route('/modula', methods=['POST'])
    def modula_request():

        # log
        logger.info('richiesta POST/modula ricevuta')

        # ricezione del JSON
        dati = request.get_json()

        # verifico che che la voce comando esista in dati
        if 'comando' in dati:

            # log
            logger.info('comando ricevuto: %s' % dati['comando'])

            # aggiungo il comando ricevuto alla risposta
            risposta = { 'comando': dati['comando'], 'status': '', 'risposta':'', 'info': [], 'errori': [] }

            # faccio il parsing del comando
            dettagli = parse_modula( dati['comando'] )

            # valuto se il dettagli[2] è nella lista [ 'CALL', 'RETURN', 'STATUS' ]
            if dettagli[2] in [ 'CALL', 'RETURN', 'STATUS' ]:

                # log
                logger.info(f'comando { dettagli[2] } ({ dati["comando"] }) ricevuto')

                # notifica di sistema
                notification.notify( title=f'comando { dettagli[2] } ricevuto', message=f'comando ricevuto: { dati["comando"] }', timeout=5 )

                # valuto il comando
                if dettagli[2] == 'CALL':

                    # invio il comando in modalità pigra
                    risultato = lazy_call( dati['comando'] )

                else:

                    # invio il comando in modalità attiva
                    risultato = send_command( dati['comando'] )

                # log
                logger.info(f'risultato della chiamata: { risultato }')

                # valutazione del risultato
                if risultato[0] == '-99':
                    risposta['errori'].append( 'errore durante l\'invio del comando' )
                elif risultato[2] == 'CALL' and risultato[3] == '-1':
                    risposta['errori'].append( 'cassetto non valido' )
                elif risultato[2] == 'CALL' and risultato[3] == '-2':
                    risposta['errori'].append( 'piazzola non valida' )
                elif risultato[2] == 'CALL' and risultato[3] == '-5':
                    risposta['errori'].append( 'login non effettuato o piazzola non attiva' )
                elif risultato[2] == 'CALL' and risultato[3] == '-6':
                    risposta['errori'].append( 'modalità automatica non inserita' )
                elif risultato[2] == 'RETURN' and risultato[3] == '-1':
                    risposta['errori'].append( 'piazzola vuota' )
                elif risultato[2] == 'RETURN' and risultato[3] == '-2':
                    risposta['errori'].append( 'piazzola non valida' )
                else:
                    risposta['risposta'] = 'comando eseguito'
                    risposta['status'] = 'OK'

            else:

                # log
                logger.error(f'comando non previsto { dettagli[2] } ({ dati["comando"] }) ricevuto')

                # aggiungo l'errore agli errori della risposta
                risposta['errori'].append( f'comando non previsto ricevuto: { dati["comando"] }' )

                # notifica di sistema
                notification.notify( title=f'comando { dettagli[2] } non valido ricevuto', message=f'comando ricevuto: { dati["comando"] }', timeout=5 )

        else:

            # log
            logger.error('comando non presente nel JSON')

            # aggiungo l'errore agli errori della risposta
            risposta['errori'].append( 'comando non presente nel JSON' )

        # restituisco la risposta in formato JSON
        return jsonify(risposta)

    # avvio del server Flask
    app.run(port=5000, threaded=True)

# funzione per l'avvio dell'icona di sistema
def run_icon():

    # log
    logger.info('avviata l\'icona di sistema (PID: %d)' % os.getpid())

    # configurazione dell'icona di sistema
    icon = Icon('GlisWeb Agent', Image.open('icon.png'), menu=pystray.Menu(
        MenuItem('informazioni', lambda: show_info(icon) ),
        MenuItem('esci', lambda: graceful_exit(icon))
    ))

    # avvio dell'icona di sistema
    icon.run()

## PROGRAMMA PRINCIPALE
#

# se mi trovo nel contesto main
if __name__ == '__main__':

    # vado in modalità silenziosa
    if system == "Linux":
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

    # abilito il freeze support
    multiprocessing.freeze_support()

    # notifica di sistema per l'avvio del programma
    notification.notify( title='GlisWeb Agent avviato', message=f'GlisWeb Agent v{versione} in esecuzione...', timeout=5 )

    # log
    logger.info('PID corrente: %d' % os.getpid())

    # avvio del server Flask
    server_process = Process(target=run_server,name='server_process')
    server_process.start()

    # aggiungo il processo alla lista dei processi
    processi.append(server_process)

    # avvio dell'icona di sistema
    icon_process = Process(target=run_icon,name='icon_process')
    icon_process.start()

    # aggiungo il processo alla lista dei processi
    processi.append(icon_process)

    # log processi in lista
    for processo in processi:
        logger.info(f'processo {processo.name} avviato con PID: {processo.pid}')

    # mando i processi in background
    if system == "Linux":
        logger.info(f'avvio per {system} PID: {os.getpid()}')
        with DaemonContext():
            server_process.join()
            icon_process.join()
    elif system == "Windows":
        logger.info(f'avvio per {system} PID: {os.getpid()}')
        server_process.join()
        icon_process.join()
    else:
        logger.error(f'sistema operativo non supportato: {system}')
        sys.exit(1)
