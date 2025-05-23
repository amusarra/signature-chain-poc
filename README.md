# Signature Chain POC con PostgreSQL e Python

[![Antonio Musarra's Blog](https://img.shields.io/badge/maintainer-Antonio_Musarra's_Blog-purple.svg?colorB=6e60cc)](https://www.dontesta.it)
[![Keep a Changelog v1.1.0 badge](https://img.shields.io/badge/changelog-Keep%20a%20Changelog%20v1.1.0-%23E05735)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Questa Proof of Concept (POC) dimostra come costruire una **signature chain**: una sequenza immutabile di firme digitali su uno stesso documento. Ogni firma è collegata alla precedente, garantendo **autenticità**, **integrità** e **sequenzialità**.

Questa POC utilizza chiavi RSA generate in memoria e non persistite. In un ambiente reale, si raccomanda l’uso di:

- HSM o key vault
- Timestamp Authority (TSA)
- Certificati validi e verificabili

## 📖 Approfondimenti

Per una comprensione dettagliata dell'architettura, del funzionamento della catena di firme, della struttura dei dati, dei meccanismi di verifica e delle considerazioni sulla sicurezza crittografica implementate in questa PoC, si rimanda all'articolo completo:

**"[La Signature Chain: Garanzia di Autenticità, Integrità e Sequenzialità nei Documenti Digitali](https://codemotion.com/magazine/link-all-articolo-quando-disponibile)"** pubblicato su Codemotion Magazine.

L'articolo approfondisce:

- L'architettura del sistema e il ruolo dei componenti.
- La struttura dettagliata della tabella `signature_chain` e il significato di ogni campo.
- Diagrammi illustrativi del flusso di creazione e verifica della catena.
- La logica di verifica dell'integrità del documento originale.
- Considerazioni sulla scelta degli algoritmi crittografici e possibili alternative.

## ⚙️ Funzionalità Principali della POC

- Firme digitali su documenti con RSA (chiavi generate in memoria).
- Catena crittografica basata su hash SHA-256.
- Verifica dell'integrità della catena di firme.
- Utilizzo di un database PostgreSQL con vincoli di integrità e Row-Level Security.
- Avvio semplificato del database tramite Podman (o Docker).

## ✅ Caratteristiche Chiave della Catena Dimostrate

- **Immutabilità**: La modifica di un blocco invalida la catena successiva.
- **Integrità del Documento**: L'hash del documento assicura che le firme si riferiscano alla stessa versione.
- **Sequenzialità Verificabile**: Il legame tra i blocchi garantisce l'ordine cronologico.
- **Autenticità del Firmatario**: Ogni firma è verificabile tramite la chiave pubblica del firmatario.

## 🚀 Come avviare la POC

### 1. Requisiti

- [Podman](https://podman.io/) (o Docker, con lievi modifiche ai comandi `podman-compose`)
- Python 3.9+
- Librerie Python: `psycopg2-binary`, `cryptography`.

Installa le dipendenze Python:

```bash
pip install -r requirements.txt
```

(Assicurati che `requirements.txt` contenga `psycopg2-binary` e `cryptography`)

### 2. Configurazione Variabili d'Ambiente (Opzionale)

Lo script `main.py` può essere configurato tramite variabili d'ambiente per i dettagli di connessione al database. Se non impostate, verranno usati valori di default.

Esempio:

```bash
export APP_DB_USER="mio_user_app"
export APP_DB_PASSWORD="mia_password_app"
export SUPER_DB_USER="postgres_admin"
export SUPER_DB_PASSWORD="admin_password"
export DB_NAME="poc_signatures"
export DB_HOST="localhost"
```

I valori di default sono: `app_user`, `app_password`, `postgres`, `postgres`, `signature_demo`, `localhost`.

### 3. Avvio del database PostgreSQL

Viene fornito un file `podman-compose.yml` per avviare un'istanza di PostgreSQL con gli utenti e il database necessari preconfigurati.

```bash
podman-compose -f podman-compose.yml up -d
```

Questo comando:

- Avvia un container PostgreSQL.
- Crea il database specificato (default: `signature_demo`).
- Crea gli utenti `app_user` (con permessi limitati) e `postgres` (superutente).
- Esegue lo script `init.sql` per creare la tabella `signature_chain` e impostare i permessi e la Row-Level Security (RLS) per `app_user`.
- Espone la porta `5432` del database sull'host.

### 4. Esegui lo script di firma e verifica

Lo script `main.py` simula due scenari principali per dimostrare il funzionamento della catena e i meccanismi di sicurezza del database:

1. Operazioni come utente applicativo con privilegi limitati (`app_user`).
2. Operazioni come utente con privilegi elevati (`super_db_user`).

```bash
python main.py
```

L'output mostrerà i dettagli di ogni operazione, inclusa la generazione delle chiavi (solo per la demo), l'inserimento dei blocchi nella catena e i risultati delle verifiche di integrità e dei tentativi di manomissione. Consultare l'articolo linkato sopra per un'interpretazione dettagliata dell'output e degli scenari.
