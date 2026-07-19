CREATE TABLE sanctions_blacklist (
    ticker VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    regulatory_body VARCHAR(50) NOT NULL,
    listed_on DATE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sanctions_ticker ON sanctions_blacklist(ticker);
