-- ========================================
-- COMPLETE FINAL DATABASE SCHEMA WITH sync_block
-- Original schema + essential optimizations + USD currency rates + sync_block tracking
-- ========================================

-- ========== CUSTOM TYPES ==========
CREATE TYPE transaction_type AS ENUM ('lend', 'withdraw', 'borrow', 'repayment', 'partial_repayment', 'liquidation');

-- ========== ADDRESSES ==========
CREATE TABLE addresses (
    id SERIAL PRIMARY KEY,
    address TEXT UNIQUE NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== USER POOL ANALYTICS ==========
CREATE TABLE user_pool_analytics (
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    total_earnt_30d NUMERIC DEFAULT 0,
    total_earnt_30d_usd NUMERIC DEFAULT 0,
    apy_earnt_30d NUMERIC DEFAULT 0,
    position_value_30d NUMERIC DEFAULT 0,
    total_earnt_90d NUMERIC DEFAULT 0,
    total_earnt_90d_usd NUMERIC DEFAULT 0,
    apy_earnt_90d NUMERIC DEFAULT 0,
    position_value_90d NUMERIC DEFAULT 0,
    total_earnt_365d NUMERIC DEFAULT 0,
    total_earnt_365d_usd NUMERIC DEFAULT 0,
    apy_earnt_365d NUMERIC DEFAULT 0,
    position_value_365d NUMERIC DEFAULT 0,
    projected_earnt_30d NUMERIC DEFAULT 0,
    projected_earnt_30d_usd NUMERIC DEFAULT 0,
    projected_apy_30d NUMERIC DEFAULT 0,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (address_id, pool_nft),
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== POOLS ==========
CREATE TABLE pools (
    nft TEXT PRIMARY KEY,
    pooled_asset TEXT NOT NULL,
    total_lent NUMERIC DEFAULT 0,
    total_borrowed NUMERIC DEFAULT 0,
    lend_apy NUMERIC DEFAULT 0,
    borrow_apy NUMERIC DEFAULT 0,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== CURRENCY RATES ==========
CREATE TABLE currency_rates (
    id SERIAL PRIMARY KEY,
    pooled_asset TEXT NOT NULL,
    usd_rate NUMERIC NOT NULL DEFAULT 0,
    timestamp BIGINT NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_asset_timestamp UNIQUE (pooled_asset, timestamp)
);


-- ========== POOL DATA HISTORICAL ==========
CREATE TABLE pool_data_historical (
    pool_nft TEXT NOT NULL,
    block_height BIGINT NOT NULL,
    transaction_id TEXT NOT NULL,
    lend_apy NUMERIC NOT NULL,
    borrow_apy NUMERIC NOT NULL,
    pool_utilization NUMERIC NOT NULL,
    total_lent NUMERIC NOT NULL,
    total_borrowed NUMERIC NOT NULL,
    box_timestamp BIGINT NOT NULL,
    pool_box_id TEXT NOT NULL,
    lend_token_value NUMERIC NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (pool_nft, block_height, transaction_id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== TRANSACTIONS ==========
CREATE TABLE transactions (
    id TEXT PRIMARY KEY,
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    type transaction_type NOT NULL,
    amount NUMERIC NOT NULL,
    fee_paid NUMERIC,
    block_height BIGINT,
    timestamp BIGINT,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== BORROW POSITIONS ==========
CREATE TABLE borrow_positions (
    box_id TEXT PRIMARY KEY,
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    amount_borrowed NUMERIC NOT NULL,
    total_owed NUMERIC NOT NULL,
    borrow_height BIGINT NOT NULL,
    last_modified_height BIGINT NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== USER LEND POSITIONS HISTORICAL ==========
CREATE TABLE user_lend_positions_historical (
    id SERIAL PRIMARY KEY,
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    block_height BIGINT NOT NULL,
    timestamp BIGINT NOT NULL,
    position_tokens NUMERIC NOT NULL,
    position_value NUMERIC NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft),
    CONSTRAINT unique_address_pool_position_block UNIQUE (address_id, pool_nft, block_height)
);

-- ========== USER DEPOSITS HISTORICAL ==========
CREATE TABLE user_deposits_historical (
    id SERIAL PRIMARY KEY,
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    transaction_id TEXT,
    block_height BIGINT NOT NULL,
    timestamp BIGINT NOT NULL,
    total_deposited NUMERIC NOT NULL,
    total_withdrawn NUMERIC NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    CONSTRAINT unique_address_pool_deposit_transaction UNIQUE (address_id, pool_nft, transaction_id)
);

-- ========== USER PORTFOLIO SNAPSHOTS ==========
CREATE TABLE user_portfolio_snapshots (
    id SERIAL PRIMARY KEY,
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    block_height BIGINT NOT NULL,
    timestamp BIGINT NOT NULL,
    position_value NUMERIC NOT NULL,
    total_profit NUMERIC NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft),
    CONSTRAINT unique_address_pool_snapshot_timestamp UNIQUE (address_id, pool_nft, timestamp)
);

-- ========================================
-- ORIGINAL INDEXES
-- ========================================

-- ========== ADDRESSES INDEXES ==========
CREATE INDEX idx_addresses_address ON addresses(address);

-- ========== CURRENCY RATES INDEXES ==========
CREATE INDEX idx_currency_rates_asset_timestamp ON currency_rates(pooled_asset, timestamp DESC);
CREATE INDEX idx_currency_rates_timestamp ON currency_rates(timestamp DESC);

-- ========== INTEREST DATA INDEXES ==========
CREATE INDEX idx_interest_data_pool_nft ON interest_data(pool_nft);
CREATE INDEX idx_interest_data_block_height ON interest_data(block_height);
CREATE INDEX idx_interest_data_transaction_id ON interest_data(transaction_id);
CREATE INDEX idx_interest_data_created_at ON interest_data(created_at);

-- ========== POOL DATA HISTORICAL INDEXES ==========
CREATE INDEX idx_pool_data_historical_pool_nft ON pool_data_historical(pool_nft);
CREATE INDEX idx_pool_data_historical_block_height ON pool_data_historical(block_height);
CREATE INDEX idx_pool_data_historical_transaction_id ON pool_data_historical(transaction_id);
CREATE INDEX idx_pool_data_historical_box_timestamp ON pool_data_historical(box_timestamp);
CREATE INDEX idx_pool_data_historical_created_at ON pool_data_historical(created_at);
CREATE INDEX idx_pool_data_historical_updated_at ON pool_data_historical(updated_at);

-- ========== TRANSACTIONS INDEXES ==========
CREATE INDEX idx_transactions_address_id ON transactions(address_id);
CREATE INDEX idx_transactions_pool_nft ON transactions(pool_nft);
CREATE INDEX idx_transactions_type ON transactions(type);
CREATE INDEX idx_transactions_block_height ON transactions(block_height);
CREATE INDEX idx_transactions_fee_paid ON transactions(fee_paid);

-- ========== BORROW POSITIONS INDEXES ==========
CREATE INDEX idx_borrow_positions_address_id ON borrow_positions(address_id);
CREATE INDEX idx_borrow_positions_pool_nft ON borrow_positions(pool_nft);

-- ========== USER LEND POSITIONS HISTORICAL INDEXES ==========
CREATE INDEX idx_user_lend_positions_address_pool ON user_lend_positions_historical(address_id, pool_nft);
CREATE INDEX idx_user_lend_positions_timestamp ON user_lend_positions_historical(timestamp DESC);
CREATE INDEX idx_user_lend_positions_block_height ON user_lend_positions_historical(block_height);

-- ========== USER DEPOSITS HISTORICAL INDEXES ==========
CREATE INDEX idx_user_deposits_address_pool_time ON user_deposits_historical(address_id, pool_nft, timestamp DESC);
CREATE INDEX idx_user_deposits_transaction ON user_deposits_historical(transaction_id);
CREATE INDEX idx_user_deposits_block_height ON user_deposits_historical(block_height);

-- ========================================
-- NEW ESSENTIAL PERFORMANCE INDEXES
-- ========================================

-- Critical index for user portfolio queries (most important)
CREATE INDEX IF NOT EXISTS idx_user_portfolio_snapshots_address_timestamp
ON user_portfolio_snapshots(address_id, timestamp DESC);

-- Critical index for user positions queries
CREATE INDEX IF NOT EXISTS idx_user_lend_positions_address_pool_timestamp
ON user_lend_positions_historical(address_id, pool_nft, timestamp DESC)
WHERE position_tokens > 0;

-- Covering index to speed up address lookups
CREATE INDEX IF NOT EXISTS idx_addresses_address_covering
ON addresses(address) INCLUDE (id);

-- ========================================
-- MAINTENANCE-FREE VIEWS
-- ========================================

-- View for latest user positions (always up-to-date)
CREATE OR REPLACE VIEW v_user_latest_positions AS
SELECT DISTINCT ON (address_id, pool_nft)
    address_id,
    pool_nft,
    position_tokens,
    position_value,
    timestamp,
    block_height,
    sync_block
FROM user_lend_positions_historical
WHERE position_tokens > 0
ORDER BY address_id, pool_nft, timestamp DESC, block_height DESC;

-- View for latest portfolio snapshots (always up-to-date)
CREATE OR REPLACE VIEW v_user_latest_portfolio AS
SELECT DISTINCT ON (address_id, pool_nft)
    address_id,
    pool_nft,
    position_value,
    total_profit,
    timestamp,
    block_height,
    sync_block
FROM user_portfolio_snapshots
ORDER BY address_id, pool_nft, timestamp DESC, block_height DESC;

-- Combined view for easy queries with currency rates
CREATE OR REPLACE VIEW v_user_portfolio_with_pools AS
SELECT
    ulp.address_id,
    ulp.pool_nft,
    p.pooled_asset,
    ulp.position_tokens,
    ulp.position_value,
    COALESCE(ups.total_profit, 0) as total_profit,
    ulp.timestamp,
    ulp.sync_block,
    cr.usd_rate,
    (ulp.position_value * cr.usd_rate) as position_value_usd
FROM v_user_latest_positions ulp
JOIN pools p ON ulp.pool_nft = p.nft
LEFT JOIN v_user_latest_portfolio ups ON ulp.address_id = ups.address_id AND ulp.pool_nft = ups.pool_nft
LEFT JOIN LATERAL (
    SELECT usd_rate
    FROM currency_rates
    WHERE pooled_asset = p.pooled_asset
    ORDER BY timestamp DESC
    LIMIT 1
) cr ON true;

-- ========================================
-- SCHEMA SUMMARY
-- ========================================

/*
TABLES: 11 total
- addresses (+ sync_block)
- user_pool_analytics (+ sync_block)
- pools (+ sync_block)
- currency_rates (+ sync_block)
- interest_data (+ sync_block)
- pool_data_historical (+ sync_block)
- transactions (+ sync_block)
- borrow_positions (+ sync_block)
- user_lend_positions_historical (+ sync_block)
- user_deposits_historical (+ sync_block)
- user_portfolio_snapshots (+ sync_block)

INDEXES: 23 total (original + performance optimizations)

VIEWS: 3 maintenance-free views (updated to include sync_block)
- v_user_latest_positions
- v_user_latest_portfolio
- v_user_portfolio_with_pools

NEW FEATURES:
- sync_block field on ALL tables for blockchain sync tracking
- Currency rates table for USD conversions
- Enhanced portfolio view with automatic USD conversion
- Blockchain data lineage tracking capability

OPTIMIZATIONS:
- Critical composite indexes for user queries
- Covering indexes to avoid table lookups
- Partial indexes for active positions only
- Always up-to-date views (no maintenance required)
- USD currency conversion calculations in views
- Block height tracking for data synchronization
*/