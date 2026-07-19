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
    const res = await client.query(`
      SELECT trigger_name 
      FROM information_schema.triggers 
      WHERE event_object_table = 'clax_compliance_worm_logs';
    `);
    console.log("Triggers on WORM table:", res.rows);
  } catch (e) {
    console.error(e);
  } finally {
    await client.end();
  }
}
run();
