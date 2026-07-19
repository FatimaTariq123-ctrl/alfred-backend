CREATE OR REPLACE FUNCTION prevent_update_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Updates and Deletes are strictly forbidden on WORM tables (SFC Schedule 7).';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER worm_insert_only
BEFORE UPDATE OR DELETE ON clax_compliance_worm_logs
FOR EACH ROW EXECUTE FUNCTION prevent_update_delete();
