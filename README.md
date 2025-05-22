# Signature Chain POC con PostgreSQL e Python

Questa Proof of Concept (POC) dimostra come costruire una **signature chain**: una sequenza immutabile di firme digitali su uno stesso documento. Ogni firma è collegata alla precedente, garantendo **autenticità**, **integrità** e **sequenzialità**.

Questa POC utilizza chiavi RSA generate in memoria e non persistite. In un ambiente reale, si raccomanda l’uso di:

- HSM o key vault
- Timestamp Authority (TSA)
- Certificati validi e verificabili

## ⚙️ Funzionalità principali

- Firme digitali su documenti con RSA
- Catena crittografica con hash SHA-256
- Verifica di integrità della catena
- Database PostgreSQL con vincoli di integrità
- Avvio del database tramite Podman

## 🧱 Architettura

Il sistema si basa su un'applicazione Python che interagisce con un database PostgreSQL per memorizzare e verificare una catena di firme digitali.

```mermaid
graph LR
    subgraph "Applicazione"
        P["🐍 Python Script<br>(main.py)"]
    end
    subgraph "Database (gestito da Podman)"
        DB[(🐘 PostgreSQL)]
        TBL[📄 Tabella: signature_chain]
    end
    USER[👤 Utente/Processo Firmatario] -- Esegue --> P
    P -- Connette e opera su --> DB
    DB -- Contiene --> TBL

    style P fill:#306998,stroke:#333,stroke-width:2px,color:#fff
    style DB fill:#2F6792,stroke:#333,stroke-width:2px,color:#fff
    style TBL fill:#ADD8E6,stroke:#333,stroke-width:2px,color:#000
    style USER fill:#FFD700,stroke:#333,stroke-width:2px,color:#000
```

Ogni firma su un documento viene registrata come un blocco nella tabella `signature_chain`. La struttura di un blocco è la seguente:

- `id` (SERIAL PRIMARY KEY): Identificativo univoco progressivo del blocco.
- `document_id` (UUID): Identificativo univoco del documento a cui si riferisce la catena di firme. Questo permette di avere catene separate per documenti diversi.
- `signer` (VARCHAR(255)): Nome o identificativo del firmatario.
- `document_hash` (VARCHAR(64)): Hash SHA-256 del contenuto del documento originale. Questo hash rimane costante per tutte le firme della stessa catena sullo stesso documento.
- `prev_hash` (VARCHAR(128), NULLABLE): Hash della firma (`signature`) del blocco precedente nella catena. Per il primo blocco (blocco genesi), questo valore è `NULL`.
- `signature` (VARCHAR(128)): Firma digitale RSA. Viene calcolata firmando la concatenazione di `prev_hash` (o una stringa vuota se `NULL`) e `document_hash` del blocco corrente. Questo campo rappresenta l'hash del blocco corrente e viene usato come `prev_hash` dal blocco successivo.
- `created_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP): Timestamp di creazione del blocco.

### Esempio di Record nella Tabella

Ecco un esempio di come potrebbero apparire i record nella tabella `signature_chain`:

#### Blocco 1 (Genesi - Firmatario: Antonio)

| Campo           | Valore                                                                 | Descrizione                                                                 |
|-----------------|------------------------------------------------------------------------|-----------------------------------------------------------------------------|
| `id`            | `1`                                                                    | Identificativo progressivo                                                  |
| `document_id`   | `c4a7a134-8a02-4bad-bc9f-395f7f0f1a33`                                  | UUID del documento                                                          |
| `signer`        | `Antonio`                                                              | Nome del firmatario                                                         |
| `document_hash` | `f2ca1bb6c7e907d06dafe4687e579fce76b37e4e93b7605022da52e6ccc26fd2`      | Hash SHA-256 del documento originale                                        |
| `prev_hash`     | `NULL`                                                                 | Essendo il primo blocco, non ha un hash precedente                          |
| `signature`     | `a3f5b1...c72e`                                                        | Firma RSA dei dati `'' + document_hash` (hash esadecimale di 128 caratteri) |
| `created_at`    | `2025-05-21 14:30:00.123456+00`                                         | Timestamp di creazione                                                      |

#### Blocco 2 (Firmatario: Marianna)

| Campo           | Valore                                                                 | Descrizione                                                                      |
|-----------------|------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| `id`            | `2`                                                                    | Identificativo progressivo                                                       |
| `document_id`   | `c4a7a134-8a02-4bad-bc9f-395f7f0f1a33`                                  | Stesso `document_id` del blocco precedente                                       |
| `signer`        | `Marianna`                                                             | Nome del firmatario                                                              |
| `document_hash` | `f2ca1bb6c7e907d06dafe4687e579fce76b37e4e93b7605022da52e6ccc26fd2`      | Stesso `document_hash` del blocco precedente                                     |
| `prev_hash`     | `a3f5b1...c72e`                                                        | La `signature` del blocco precedente (quello di Antonio)                         |
| `signature`     | `b8e0d9...f4a1`                                                        | Firma RSA dei dati `prev_hash + document_hash` (hash esadecimale di 128 caratteri) |
| `created_at`    | `2025-05-21 14:35:00.654321+00`                                         | Timestamp di creazione                                                           |

### Schema della Catena di Firme

Il diagramma seguente illustra come i blocchi sono concatenati:

```mermaid
graph TD
    subgraph "Documento Originale"
        DOC[📄 Documento: doc.txt]
        H_DOC["🔍 SHA-256(doc.txt)<br/>(document_hash)"]
        DOC --> H_DOC
    end

    subgraph "Blocco 1 (Genesi)"
        B1_SIGNER["👤 Firmatario: Antonio"]
        B1_PREV_HASH["prev_hash: NULL"]
        B1_DATA_TO_SIGN["Dati Firmati:<br/>'' + document_hash"]
        B1_SIGNATURE["🔑 Signature 1<br/>(hash del Blocco 1)"]
        B1_SIGNER --> B1_PREV_HASH
        B1_PREV_HASH --> B1_DATA_TO_SIGN
        H_DOC --> B1_DATA_TO_SIGN
        B1_DATA_TO_SIGN -- Firma con Chiave Privata Antonio --> B1_SIGNATURE
    end

    subgraph "Blocco 2"
        B2_SIGNER["👤 Firmatario: Marianna"]
        B2_PREV_HASH["prev_hash: Signature 1"]
        B2_DATA_TO_SIGN["Dati Firmati:<br/>Signature 1 + document_hash"]
        B2_SIGNATURE["🔑 Signature 2<br/>(hash del Blocco 2)"]
        B2_SIGNER --> B2_PREV_HASH
        B1_SIGNATURE --> B2_PREV_HASH
        B2_PREV_HASH --> B2_DATA_TO_SIGN
        H_DOC --> B2_DATA_TO_SIGN
        B2_DATA_TO_SIGN -- Firma con Chiave Privata Marianna --> B2_SIGNATURE
    end

    subgraph "Blocco 3"
        B3_SIGNER["👤 Firmatario: Claudio"]
        B3_PREV_HASH["prev_hash: Signature 2"]
        B3_DATA_TO_SIGN["Dati Firmati:<br/>Signature 2 + document_hash"]
        B3_SIGNATURE["🔑 Signature 3<br/>(hash del Blocco 3)"]
        B3_SIGNER --> B3_PREV_HASH
        B2_SIGNATURE --> B3_PREV_HASH
        B3_PREV_HASH --> B3_DATA_TO_SIGN
        H_DOC --> B3_DATA_TO_SIGN
        B3_DATA_TO_SIGN -- Firma con Chiave Privata Claudio --> B3_SIGNATURE
    end

    B1_SIGNATURE -.-> B2_PREV_HASH
    B2_SIGNATURE -.-> B3_PREV_HASH
    B3_SIGNATURE --> END([🏁 Fine Catena])

    style DOC fill:#ECECEC,stroke:#333,stroke-width:2px
    style H_DOC fill:#ECECEC,stroke:#333,stroke-width:2px
```

### ✅ Caratteristiche Chiave della Catena

- **Immutabilità**: Una volta che un blocco è aggiunto, la sua `signature` dipende dal contenuto e dal blocco precedente. Modificare un blocco precedente invaliderebbe l'intera catena successiva.
- **Integrità del Documento**: `document_hash` assicura che tutte le firme si riferiscano alla stessa versione del documento.
- **Sequenzialità Verificabile**: `prev_hash` crea un legame cronologico tra le firme.
- **Autenticità del Firmatario**: Ogni `signature` è creata con la chiave privata del firmatario e può essere verificata con la sua chiave pubblica.

## 🚀 Come avviare la POC

### 1. Requisiti

- [Podman](https://podman.io/) (o Docker, con lievi modifiche ai comandi `podman-compose`)
- Python 3.9+
- Librerie Python: `psycopg2-binary`, `cryptography` (assicurati che `psycopg2-binary` sia usato per facilità di installazione locale invece di `psycopg2` che potrebbe richiedere dipendenze di compilazione).

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

Lo script `main.py` simula i seguenti scenari:

1. **Scenario Utente Applicativo (`app_user`)**:
    - Connessione al DB come `app_user`.
    - Inserimento di una sequenza di firme da parte di diversi firmatari (Antonio, Marianna, Claudio) sullo stesso documento.
    - Verifica dell'integrità della catena.
    - Tentativo (fallito, grazie a RLS e GRANT) di manomettere un record esistente da parte di `app_user`.
    - Nuova verifica della catena.
2. **Scenario Utente Privilegiato (`super_db_user`, default: `postgres`)**:
    - Pulizia della tabella.
    - Connessione al DB come utente con privilegi elevati.
    - Reinserimento della sequenza di firme.
    - Verifica dell'integrità della catena.
    - Tentativo (riuscito) di manomettere un record esistente da parte del superutente.
    - Nuova verifica della catena, che **dovrebbe fallire**, evidenziando la manomissione.

```bash
python main.py
```

### 5. Verifica della Catena

La funzione `verify_chain` nello script:

1. Recupera tutti i record dalla tabella `signature_chain` in ordine di ID.
2. Per ogni record:
    a. Controlla che `prev_hash` corrisponda alla `signature` del record precedente (a meno che non sia il blocco genesi, dove `prev_hash` deve essere `NULL`).
    b. Ricostruisce i dati che sono stati originariamente firmati: `(prev_hash || document_hash)`.
    c. Verifica la `signature` del record corrente usando i dati ricostruiti e la chiave pubblica del `signer` associato a quel record.
3. Se una qualsiasi di queste verifiche fallisce, l'intera catena è considerata compromessa.

### Output Atteso (Estratto)

L'output sarà colorato e includerà emoji per indicare lo stato delle operazioni. Un esempio parziale:

```text
💾 Tentativo di pulire la tabella signature_chain come utente 'postgres'...
✅ Tabella signature_chain pulita con successo.

===== SCENARIO 1: Utente Applicativo (app_user) =====
💾 Tentativo di connessione al database 'signature_demo' come utente 'app_user'...
✅ Connessione come app_user riuscita.

🔗==== Sequenza Firme Inserite nella Catena ====
ℹ️ Documento Originale: "Contenuto documento firmato da più persone"
ℹ️ Hash Documento Originale: <hash_del_documento>
----------------------------------------------------------------------
🧱 ID Blocco: 1
  Firmatario: Antonio
  Hash Documento Firmato: <hash_del_documento>
  Hash Catena Precedente: N/A (Blocco Genesi)
  Hash Catena Corrente (Firma del Blocco): <signature_blocco_1>...
----------------------------------------------------------------------
🧱 ID Blocco: 2
  Firmatario: Marianna
  Hash Documento Firmato: <hash_del_documento>
  Hash Catena Precedente: <signature_blocco_1>
  Hash Catena Corrente (Firma del Blocco): <signature_blocco_2>...
----------------------------------------------------------------------
... (altre firme e output di verifica) ...

🔗==== Verifica Integrità Catena Firme (Contesto: app_user - Post Inserimento) ====
...
✅ La catena delle firme è VALIDA. Integrità CONFERMATA. ✅
----------------------------------------------------------------------

⚠️---- 1.2 Tentativo di Manomissione UPDATE (come app_user) ----
ℹ️ Tentativo di UPDATE del document_hash del blocco ID: 2 (Firmatario: Marianna) come 'app_user'.
✅ SUCCESSO: Tentativo di UPDATE BLOCCATO dal DB per 'app_user' come previsto!
  ℹ️ Errore DB (SQLSTATE 42501): permission denied for table signature_chain
... (output scenario superuser con manomissione e fallimento verifica crittografica) ...

🏁Fine della dimostrazione.
```
