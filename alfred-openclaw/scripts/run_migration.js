const fs = require('fs');
const { Client } = require('pg');

const env = fs.readFileSync('.env', 'utf8');
const neonUrlMatch = env.match(/NEON_DATABASE_URL=(.*)/);
if (!neonUrlMatch) throw new Error("No URL");

const client = new Client({
  connectionString: neonUrlMatch[1].trim()
});

async function run() {
  await client.connect();
  try {
    await client.query(`
      CREATE OR REPLACE FUNCTION prevent_update_delete()
      RETURNS TRIGGER AS $$
      BEGIN
          RAISE EXCEPTION 'Updates and Deletes are strictly forbidden on WORM tables (SFC Schedule 7).';
      END;
      $$ LANGUAGE plpgsql;

      DROP TRIGGER IF EXISTS worm_insert_only ON clax_compliance_worm_logs;
      CREATE TRIGGER worm_insert_only
      BEFORE UPDATE OR DELETE ON clax_compliance_worm_logs
      FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
    `);
    console.log("WORM trigger created successfully.");
  } catch (e) {
    console.error(e);
  } finally {
    await client.end();
  }
}
run();
