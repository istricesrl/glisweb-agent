## IMPORTAZIONE LIBRERIE
#

# librerie di utilità generale
import sys, os
import platform
import configparser
import logging

# librerie per data e ora
import time

# librerie per l'interfaccia grafica
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QMainWindow
from PyQt5.QtGui import QIcon

# librerie per il multiprocessing
import threading
from multiprocessing import Process
from multiprocessing import Manager

# librerie per i timer
from PyQt5.QtCore import QTimer

# librerie per la gestione delle chiamate API tramite Flask
from flask import Flask, jsonify, request

## CONFIGURAZIONI GLOBALI
#

# trovo il sistema operativo
system = platform.system()

# numero di versione
versione = '0.2.1'

# lettura del file di configurazione
try:
    config = configparser.ConfigParser()
    config.read_file( open( 'config.ini' ) )
    
except FileNotFoundError:
    print('file di configurazione non trovato, esco')
    sys.exit(1)

# formato del log
logformat = '%(asctime)s [%(levelname)s] %(filename)s: %(message)s'

# configurazione del logger
logger = logging.getLogger(__name__)
logging.basicConfig(filename='agent.log', format=logformat, level=logging.INFO)

# log
logger.info(f'avvio GlisWeb agent per {config["generale"]["deploy"]} v{versione} su {system}')

# manager per la condivisione di dati tra processi
global manager, process_data
manager = Manager()
process_data = manager.dict()

# inizializzazione del server Flask
app_flask = Flask(__name__)

## DEFINIZIONE DELLE CLASSI
#

# classe per l'applicazione principale
class TrayApp(QMainWindow):

    # costruttore
    def __init__(self):
        super().__init__()

        # creo l'icona per il system tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.png"))

        # Mostra la notifica di avvio
        QTimer.singleShot(500, lambda: self.show_system_notification("GlisWeb agent", "avviato"))
        
        # creo il menu contestuale
        self.create_tray_menu()

        # imposto l'avvio minimizzato
        self.tray_icon.show()
        self.hide()

    # metodo per creare il menu contestuale
    def create_tray_menu(self):

        # creo il menu contestuale
        tray_menu = QMenu()

        # aggiungo la voce "apri"
        show_action = QAction("apri", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)

        # aggiungo la voce "esci"
        exit_action = QAction("esci", self)
        exit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(exit_action)

        # assegno il menu all'icona del system tray
        self.tray_icon.setContextMenu(tray_menu)

    # funzione per le notifiche di sistema
    def show_system_notification(self, title, message):

        # mostro la notifica
        self.tray_icon.showMessage( title, message, QSystemTrayIcon.Information, 3000 )

## FUNZIONI PER IL SERVER FLASK
#

# funzione per l'avvio del server Flask
def run_flask():

    # log
    logger.info('avviato il server Flask')

    # avvio del server Flask
    app_flask.run(port=5000)

# route per il preflight CORS
@app_flask.after_request
def after_request(risposta):

    # log
    logger.info('richiesta CORS')

    # header HTTP da restituire
    risposta.headers.add('Access-Control-Allow-Origin', '*')
    risposta.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    risposta.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')

    # restituisco la risposta
    return risposta

# route di test (echo server)
@app_flask.route('/echo', methods=['POST'])
def api_echo():

    # log
    logger.info('richiesta POST/echo ricevuta')

    # ricezione del JSON
    dati = request.get_json()

    # preparo la risposta
    risposta = { 'status': 'OK', 'info': [], 'errori': [] }

    # unisco i dati alla risposta
    risposta['info'].append(dati)
    
    # restituisco la risposta
    return jsonify(risposta)

# route per la gestione dell'avvio di un job di esempio
@app_flask.route('/testjobstart', methods=['POST'])
def api_test_job_start():

    # log
    logger.info('richiesta di avvio di un job di test')

    # ricezione del JSON
    dati = request.get_json()

    # aggiungo il comando ricevuto alla risposta
    risposta = { 'status': '', 'info': [], 'errori': [] }

    # verifico che che la voce comando esista in dati
    if 'comando' in dati:

        # log
        logger.info(f'comando ricevuto: {dati["comando"]}')

        # creazione ID del processo
        process_id = str(int(time.time()))

        process_data[process_id] = manager.dict()

        process_data[process_id]['status'] = 'created'
        process_data[process_id]['document_name'] = None
        process_data[process_id]['error'] = None

        # avvio il sottoprocesso per l'acquisizione dell'immagine
        p = Process(target=test_job, args=(process_id,))
        p.start()

        # rispondo al client con l'ID del processo
        risposta['status'] = 'OK'
        risposta['process_id'] = process_id
        risposta['info'].append( 'job di test avviato' )

    else:

        # log
        logger.error('comando non presente nel JSON')

        # aggiungo l'errore agli errori della risposta
        risposta['errori'].append( 'comando non presente nel JSON' )

    # restituisco la risposta in formato JSON
    return jsonify(risposta)

## PROGRAMMA PRINCIPALE
#

# esecuzione del programma
if __name__ == "__main__":

    # log
    logger.info(f'avvio processo principale (PID: %d)' % os.getpid())

    # vado in modalità silenziosa
    if system == "Linux":
        sys.stdout = open("run.log", "w")
        sys.stderr = open("run.log", "w")

    # avvio il server Flask in un thread separato
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # creo l'applicazione
    app = QApplication(sys.argv)

    # inibisco la chiusura dell'applicazione quando si chiude l'ultima finestra
    app.setQuitOnLastWindowClosed(False)

    # avvio l'applicazione principale
    window = TrayApp()

    # eseguo l'applicazione
    sys.exit(app.exec_())
