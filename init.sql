CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Creazione di un utente specifico per l'applicazione con privilegi limitati
DO
$do$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'app_user') THEN

      CREATE ROLE app_user WITH LOGIN PASSWORD 'app_password';
   END IF;
END
$do$;

GRANT CONNECT ON DATABASE signature_demo TO app_user;
GRANT USAGE ON SCHEMA public TO app_user; -- Assumendo che la tabella sia nello schema public

CREATE TABLE signature_chain (
    id SERIAL PRIMARY KEY,
    document_id UUID NOT NULL,
    signer TEXT NOT NULL,
    signed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    document_hash TEXT NOT NULL,
    prev_hash TEXT,
    chain_hash TEXT GENERATED ALWAYS AS ( -- Questa colonna non è usata attivamente nello script Python per la logica della catena, ma la lasciamo se serve per altri scopi
        encode(digest(coalesce(prev_hash, '') || document_hash, 'sha256'), 'hex')
    ) STORED,
    signature TEXT NOT NULL
);

-- Concedi solo i permessi necessari all'utente dell'applicazione
GRANT SELECT, INSERT ON signature_chain TO app_user;
GRANT USAGE ON SEQUENCE signature_chain_id_seq TO app_user;

ALTER TABLE signature_chain ENABLE ROW LEVEL SECURITY;
ALTER TABLE signature_chain FORCE ROW LEVEL SECURITY; -- Forza RLS anche per il proprietario della tabella

-- Policy per PERMETTERE INSERT a PUBLIC (e quindi a app_user)
-- Questa policy permette a chiunque abbia il permesso INSERT a livello di tabella di inserire righe.
CREATE POLICY allow_inserts_for_public ON signature_chain
    FOR INSERT TO PUBLIC
    WITH CHECK (true); -- WITH CHECK (true) significa che tutti gli insert sono permessi dalla RLS

-- Policy per PERMETTERE SELECT a PUBLIC
CREATE POLICY allow_select_for_public ON signature_chain
    FOR SELECT TO PUBLIC
    USING (true); -- USING (true) significa che tutte le righe sono visibili

-- Policy per IMPEDIRE UPDATE a PUBLIC
CREATE POLICY no_updates_for_public ON signature_chain
    FOR UPDATE TO PUBLIC
    USING (false); -- USING (false) significa che nessuna riga esistente può essere aggiornata

-- Policy per IMPEDIRE DELETE a PUBLIC
CREATE POLICY no_deletes_for_public ON signature_chain
    FOR DELETE TO PUBLIC
    USING (false); -- USING (false) significa che nessuna riga esistente può essere cancellata

-- Revoca esplicita per PUBLIC (best practice, anche se RLS dovrebbe già bloccare UPDATE/DELETE)
-- Manteniamo SELECT e INSERT per app_user come concesso sopra.
REVOKE UPDATE, DELETE ON signature_chain FROM PUBLIC;
