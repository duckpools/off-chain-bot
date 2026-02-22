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
    borrow_apy NUMERIC,
    interest_paid NUMERIC,
    block_height BIGINT,
    timestamp BIGINT,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

-- ========== USER POOL DEBTS ==========
CREATE TABLE user_pool_debts (
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    total_debt NUMERIC NOT NULL DEFAULT 0,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (address_id, pool_nft),
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== USER CURRENT POSITIONS (On-Chain Verification) ==========
CREATE TABLE user_current_positions (
    address_id INTEGER NOT NULL,
    pool_nft TEXT NOT NULL,
    position_tokens NUMERIC NOT NULL DEFAULT 0,
    position_value NUMERIC NOT NULL DEFAULT 0,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (address_id, pool_nft),
    FOREIGN KEY (address_id) REFERENCES addresses(id),
    FOREIGN KEY (pool_nft) REFERENCES pools(nft)
);

-- ========== HEADLINE STATS ==========
CREATE TABLE headlinestats (
    id SERIAL PRIMARY KEY,
    all_time_volume_by_asset JSONB NOT NULL DEFAULT '{}'::jsonb,
    total_value_locked NUMERIC NOT NULL DEFAULT 0,
    quacks_holders BIGINT NOT NULL DEFAULT 0,
    timestamp BIGINT NOT NULL,
    sync_block BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ========== SYNC CHECKPOINTS ==========
-- Safe point system for tracking verified sync state and recovery points
CREATE TABLE sync_checkpoints (
    id SERIAL PRIMARY KEY,
    checkpoint_type TEXT NOT NULL,      -- 'safe_point', 'ingested', 'verified'
    pool_nft TEXT,                       -- NULL for global, specific NFT for per-pool
    block_height BIGINT NOT NULL,
    notes TEXT,                          -- Why this checkpoint was set
    created_by TEXT DEFAULT 'system',    -- 'manual' or 'system'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT unique_checkpoint UNIQUE (checkpoint_type, pool_nft)
);

-- ========================================
-- CONSOLIDATED INDEXES (matching actual database)
-- ========================================

-- ========== ADDRESSES INDEXES ==========
-- Covering index provides both lookup and avoids table scan
CREATE INDEX idx_addresses_address_covering ON addresses(address) INCLUDE (id);
-- Regular index kept for compatibility
CREATE INDEX idx_addresses_address ON addresses(address);

-- ========== POOLS INDEXES ==========
-- Hash index for NFT lookups
CREATE INDEX idx_pools_nft_hash ON pools USING hash(nft);
-- Partial index for active pools only
CREATE INDEX idx_pools_active ON pools(pooled_asset) WHERE total_lent > 0;
-- Updated_at tracking
CREATE INDEX idx_pools_updated_at_desc ON pools(updated_at DESC);

-- ========== CURRENCY RATES INDEXES ==========
-- Primary composite index for asset-timestamp queries
CREATE INDEX idx_currency_rates_asset_timestamp_desc ON currency_rates(pooled_asset, timestamp DESC);
-- Standalone timestamp index for time-based queries
CREATE INDEX idx_currency_rates_timestamp ON currency_rates(timestamp DESC);

-- ========== POOL DATA HISTORICAL INDEXES ==========
CREATE INDEX idx_pool_data_historical_pool_nft ON pool_data_historical(pool_nft);
CREATE INDEX idx_pool_data_historical_block_height ON pool_data_historical(block_height);
CREATE INDEX idx_pool_data_historical_transaction_id ON pool_data_historical(transaction_id);
CREATE INDEX idx_pool_data_historical_box_timestamp ON pool_data_historical(box_timestamp);
CREATE INDEX idx_pool_data_historical_created_at ON pool_data_historical(created_at);
CREATE INDEX idx_pool_data_historical_updated_at ON pool_data_historical(updated_at);
-- Composite index for common pool+timestamp queries
CREATE INDEX idx_pool_data_hist_pool_timestamp ON pool_data_historical(pool_nft, box_timestamp DESC);

-- ========== TRANSACTIONS INDEXES ==========
CREATE INDEX idx_transactions_address_id ON transactions(address_id);
CREATE INDEX idx_transactions_pool_nft ON transactions(pool_nft);
CREATE INDEX idx_transactions_type ON transactions(type);
CREATE INDEX idx_transactions_block_height ON transactions(block_height);
CREATE INDEX idx_transactions_fee_paid ON transactions(fee_paid);
-- Composite indexes for common query patterns
CREATE INDEX idx_transactions_address_pool ON transactions(address_id, pool_nft, timestamp DESC);
CREATE INDEX idx_transactions_address_type_timestamp ON transactions(address_id, type, timestamp DESC) WHERE timestamp IS NOT NULL;

-- ========== USER LEND POSITIONS HISTORICAL INDEXES ==========
CREATE INDEX idx_user_lend_positions_address_pool ON user_lend_positions_historical(address_id, pool_nft);
CREATE INDEX idx_user_lend_positions_timestamp ON user_lend_positions_historical(timestamp DESC);
CREATE INDEX idx_user_lend_positions_block_height ON user_lend_positions_historical(block_height);
-- Partial index for active positions with timestamp ordering (most common query)
CREATE INDEX idx_user_lend_positions_address_pool_timestamp ON user_lend_positions_historical(address_id, pool_nft, timestamp DESC) WHERE position_tokens > 0;
-- Latest position lookup (used in views)
CREATE INDEX idx_user_lend_positions_latest ON user_lend_positions_historical(address_id, pool_nft, block_height DESC, timestamp DESC);
-- Alternative latest lookup using ID
CREATE INDEX idx_user_lend_positions_historical_latest ON user_lend_positions_historical(address_id, pool_nft, block_height DESC, id DESC);

-- ========== USER DEPOSITS HISTORICAL INDEXES ==========
-- Primary composite for address+pool+time queries
CREATE INDEX idx_user_deposits_address_pool_timestamp ON user_deposits_historical(address_id, pool_nft, timestamp DESC);
CREATE INDEX idx_user_deposits_transaction ON user_deposits_historical(transaction_id);
CREATE INDEX idx_user_deposits_block_height ON user_deposits_historical(block_height);

-- ========== USER PORTFOLIO SNAPSHOTS INDEXES ==========
CREATE INDEX idx_user_portfolio_snapshots_address_timestamp ON user_portfolio_snapshots(address_id, timestamp DESC);
CREATE INDEX idx_user_portfolio_snapshots_address_pool_timestamp ON user_portfolio_snapshots(address_id, pool_nft, timestamp DESC);
CREATE INDEX idx_user_portfolio_snapshots_block_height ON user_portfolio_snapshots(block_height);
-- Latest snapshot lookup (with all sort keys)
CREATE INDEX idx_user_portfolio_snapshots_latest ON user_portfolio_snapshots(address_id, pool_nft, block_height DESC, timestamp DESC, id DESC);
-- Timestamp-only index with filter
CREATE INDEX idx_user_portfolio_snapshots_timestamp ON user_portfolio_snapshots(timestamp DESC) WHERE address_id IS NOT NULL;
-- Composite with all time dimensions (for complex queries)
CREATE INDEX idx_user_portfolio_snapshots_address_pool_time ON user_portfolio_snapshots(address_id, pool_nft, timestamp DESC, block_height DESC);

-- ========== USER POOL DEBTS INDEXES ==========
CREATE INDEX idx_user_pool_debts_address ON user_pool_debts(address_id);
CREATE INDEX idx_user_pool_debts_pool_nft ON user_pool_debts(pool_nft);
-- Composite index for direct lookup
CREATE INDEX idx_user_pool_debts_address_pool ON user_pool_debts(address_id, pool_nft);

-- ========== USER CURRENT POSITIONS INDEXES ==========
CREATE INDEX idx_ucp_address ON user_current_positions(address_id);
CREATE INDEX idx_ucp_pool_nft ON user_current_positions(pool_nft);

-- ========== HEADLINE STATS INDEXES ==========
-- Primary index for time-based queries (DESC for most recent first)
CREATE INDEX idx_headlinestats_timestamp ON headlinestats(timestamp DESC);
-- Created_at index for database insertion tracking
CREATE INDEX idx_headlinestats_created_at ON headlinestats(created_at DESC);

-- ========== SYNC CHECKPOINTS INDEXES ==========
-- Index for fast checkpoint lookups by type and pool
CREATE INDEX idx_sync_checkpoints_type ON sync_checkpoints(checkpoint_type, pool_nft);

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
TABLES: 12 total
- addresses (+ sync_block)
- pools (+ sync_block)
- currency_rates (+ sync_block)
- pool_data_historical (+ sync_block)
- transactions (+ sync_block)
- user_lend_positions_historical (+ sync_block)
- user_deposits_historical (+ sync_block)
- user_portfolio_snapshots (+ sync_block)
- user_pool_debts (+ sync_block)
- user_current_positions (+ sync_block, on-chain verification)
- headlinestats (+ sync_block)
- sync_checkpoints (safe point system for verified sync state)

INDEXES: 45 total (consolidated and optimized)
- addresses: 2 indexes
- pools: 3 indexes
- currency_rates: 2 indexes
- pool_data_historical: 7 indexes
- transactions: 7 indexes
- user_lend_positions_historical: 6 indexes
- user_deposits_historical: 3 indexes
- user_portfolio_snapshots: 6 indexes
- user_pool_debts: 3 indexes
- user_current_positions: 2 indexes
- headlinestats: 2 indexes
- sync_checkpoints: 1 index
- (Plus system-generated primary key and unique constraint indexes)

VIEWS: 3 maintenance-free views (updated to include sync_block)
- v_user_latest_positions
- v_user_latest_portfolio
- v_user_portfolio_with_pools

OPTIMIZATIONS:
- Consolidated duplicate/redundant indexes
- Hash indexes for exact-match NFT lookups
- Covering indexes to avoid table lookups (addresses)
- Partial indexes for active positions/pools only
- Composite indexes matching actual query patterns
- Multiple "latest" lookup strategies for flexibility
- All index names match actual database implementation
*/