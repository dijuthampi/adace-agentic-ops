-- AdAce Amazon Ads Sandbox MySQL Schema & Seed Data
-- Sprint 1: Production-Accurate Mirror with Multi-Tenant Realistic Test Scenarios

SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- Table: sellers
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `sellers`;
CREATE TABLE `sellers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_name` VARCHAR(255) NOT NULL,
    `seller_type` VARCHAR(50) NOT NULL DEFAULT 'seller',
    `account_id` VARCHAR(100) NOT NULL,
    `profile_id` VARCHAR(100) NOT NULL,
    `max_bid_cap` DECIMAL(10,2) NOT NULL DEFAULT 50.00,
    `max_budget_cap` DECIMAL(10,2) NOT NULL DEFAULT 2000.00,
    `neg_key_max_no_orders` INT NOT NULL DEFAULT 10,
    `activated` TINYINT(1) NOT NULL DEFAULT 1,
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_sellers_status` (`status`),
    INDEX `idx_sellers_account_id` (`account_id`),
    INDEX `idx_sellers_profile_id` (`profile_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: seller_communication_management
-- Guardrail options: 1 = Pre-approved (autonomous execution), 2 = Approval required (HITL required)
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `seller_communication_management`;
CREATE TABLE `seller_communication_management` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_id` INT NOT NULL,
    `day_parting_option` TINYINT NOT NULL DEFAULT 1,
    `increase_budget_option` TINYINT NOT NULL DEFAULT 2 COMMENT '1=Pre-approved, 2=Approval required',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_seller_comm_seller_id` (`seller_id`),
    CONSTRAINT `fk_seller_comm_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: campaigns
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `campaigns`;
CREATE TABLE `campaigns` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_id` INT NOT NULL,
    `campaign_name` VARCHAR(255) NOT NULL,
    `campaign_str_id` VARCHAR(100) NOT NULL,
    `campaign_type` VARCHAR(50) NOT NULL DEFAULT 'sp',
    `targeting_type` VARCHAR(50) NOT NULL DEFAULT 'manual',
    `state` VARCHAR(50) NOT NULL DEFAULT 'enabled',
    `budget_type` VARCHAR(50) NOT NULL DEFAULT 'daily',
    `budget` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `status` VARCHAR(50) NOT NULL DEFAULT 'active',
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_campaigns_seller_id` (`seller_id`),
    INDEX `idx_campaigns_campaign_str_id` (`campaign_str_id`),
    INDEX `idx_campaigns_state` (`state`),
    CONSTRAINT `fk_campaigns_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: campaign_optimizers
-- Includes the critical 'dnt' (Do Not Touch) flag and target_acos
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `campaign_optimizers`;
CREATE TABLE `campaign_optimizers` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_id` INT NOT NULL,
    `campaign_id` INT NOT NULL,
    `campaign_str_id` VARCHAR(100) NOT NULL,
    `dnt` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=Do Not Touch, 0=Allow optimization',
    `daily_budget` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `budget_rule` VARCHAR(100) NOT NULL DEFAULT 'standard',
    `target_acos` DECIMAL(5,2) NOT NULL DEFAULT 25.00,
    `neg_term_opt` TINYINT(1) NOT NULL DEFAULT 1,
    `neg_key_max_no_orders` INT NOT NULL DEFAULT 10,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_optimizer_campaign_id` (`campaign_id`),
    INDEX `idx_optimizer_seller_id` (`seller_id`),
    INDEX `idx_optimizer_dnt` (`dnt`),
    CONSTRAINT `fk_optimizer_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_optimizer_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `campaigns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: campaign_metrics
-- Daily aggregated campaign performance metrics
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `campaign_metrics`;
CREATE TABLE `campaign_metrics` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `campaign_id` INT NOT NULL,
    `seller_id` INT NOT NULL,
    `campaign_str_id` VARCHAR(100) NOT NULL,
    `campaign_status` VARCHAR(50) NOT NULL DEFAULT 'enabled',
    `campaign_budget` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `status_date` DATE NOT NULL,
    `impressions` INT NOT NULL DEFAULT 0,
    `clicks` INT NOT NULL DEFAULT 0,
    `spend` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `acos` DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `orders` INT NOT NULL DEFAULT 0,
    `sales` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `roas` DECIMAL(6,2) NOT NULL DEFAULT 0.00,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_metrics_seller_date` (`seller_id`, `status_date`),
    INDEX `idx_metrics_campaign_date` (`campaign_id`, `status_date`),
    CONSTRAINT `fk_metrics_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_metrics_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `campaigns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: keyword_reports
-- Keyword level bids and performance
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `keyword_reports`;
CREATE TABLE `keyword_reports` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_id` INT NOT NULL,
    `campaign_str_id` VARCHAR(100) NOT NULL,
    `ad_group_id` VARCHAR(100) NOT NULL,
    `keyword_id` VARCHAR(100) NOT NULL,
    `keyword_text` VARCHAR(255) NOT NULL,
    `match_type` VARCHAR(50) NOT NULL,
    `state` VARCHAR(50) NOT NULL DEFAULT 'enabled',
    `bid` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `status_date` DATE NOT NULL,
    `impressions` INT NOT NULL DEFAULT 0,
    `clicks` INT NOT NULL DEFAULT 0,
    `spend` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `acos` DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `orders` INT NOT NULL DEFAULT 0,
    `sales` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `roas` DECIMAL(6,2) NOT NULL DEFAULT 0.00,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_keywords_seller_date` (`seller_id`, `status_date`),
    INDEX `idx_keywords_campaign_str` (`campaign_str_id`),
    INDEX `idx_keywords_keyword_id` (`keyword_id`),
    CONSTRAINT `fk_keywords_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: search_terms
-- Customer search terms for Tier 1 negative harvesting
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `search_terms`;
CREATE TABLE `search_terms` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `seller_id` INT NOT NULL,
    `date` DATE NOT NULL,
    `campaign_id` INT NOT NULL,
    `adgroup_id` VARCHAR(100) NOT NULL,
    `keyword_id` VARCHAR(100) NOT NULL,
    `campaign_name` VARCHAR(255) NOT NULL,
    `adgroup_name` VARCHAR(255) NOT NULL,
    `keyword` VARCHAR(255) NOT NULL,
    `match_type` VARCHAR(50) NOT NULL,
    `search_term` VARCHAR(255) NOT NULL,
    `impressions` INT NOT NULL DEFAULT 0,
    `clicks` INT NOT NULL DEFAULT 0,
    `cost` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `sales_7d` DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    `units_sold_clicks_7d` INT NOT NULL DEFAULT 0,
    `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_search_terms_seller_date` (`seller_id`, `date`),
    INDEX `idx_search_terms_campaign_id` (`campaign_id`),
    INDEX `idx_search_terms_term` (`search_term`),
    CONSTRAINT `fk_search_terms_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_search_terms_campaign` FOREIGN KEY (`campaign_id`) REFERENCES `campaigns` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- Table: adace_status_logs
-- Audit log of actions taken or proposed by AdAce engines
-- -----------------------------------------------------------------------------
DROP TABLE IF EXISTS `adace_status_logs`;
CREATE TABLE `adace_status_logs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `run_date` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `seller_id` INT NOT NULL,
    `module_id` INT NOT NULL DEFAULT 1,
    `action_id` INT NOT NULL DEFAULT 1,
    `status_text` TEXT NOT NULL,
    `rule` VARCHAR(100) DEFAULT NULL,
    `campaign_str_id` VARCHAR(100) DEFAULT NULL,
    `campaign_prv_budget` DECIMAL(10,2) DEFAULT NULL,
    `campaign_cur_budget` DECIMAL(10,2) DEFAULT NULL,
    `ad_grp_prev_bid` DECIMAL(10,2) DEFAULT NULL,
    `ad_grp_cur_bid` DECIMAL(10,2) DEFAULT NULL,
    `keywd_prev_bid` DECIMAL(10,2) DEFAULT NULL,
    `keywd_cur_bid` DECIMAL(10,2) DEFAULT NULL,
    `neg_keywd_product` VARCHAR(255) DEFAULT NULL,
    `impressions` INT DEFAULT 0,
    `clicks` INT DEFAULT 0,
    `cpc` DECIMAL(10,2) DEFAULT 0.00,
    `cost` DECIMAL(10,2) DEFAULT 0.00,
    `orders` INT DEFAULT 0,
    INDEX `idx_status_logs_seller_date` (`seller_id`, `run_date`),
    INDEX `idx_status_logs_campaign_str` (`campaign_str_id`),
    CONSTRAINT `fk_status_logs_seller` FOREIGN KEY (`seller_id`) REFERENCES `sellers` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
-- SEED DATA: Realistic Multi-Tenant Scenarios
-- =============================================================================

-- -----------------------------------------------------------------------------
-- SELLER 1: Navla Naturals (id = 1)
-- Guardrails: max_bid_cap = 25.00, max_budget_cap = 2000.00, neg_key_max_no_orders = 8
-- Communication: increase_budget_option = 2 (Requires Human-In-The-Loop Approval!)
-- -----------------------------------------------------------------------------
INSERT INTO `sellers` (`id`, `seller_name`, `seller_type`, `account_id`, `profile_id`, `max_bid_cap`, `max_budget_cap`, `neg_key_max_no_orders`, `activated`, `status`)
VALUES (1, 'Navla Naturals', 'seller', 'A3NAVLANATURALS', 'PROF_NAVLA_001', 25.00, 2000.00, 8, 1, 'active');

INSERT INTO `seller_communication_management` (`id`, `seller_id`, `day_parting_option`, `increase_budget_option`)
VALUES (1, 1, 1, 2);

-- -----------------------------------------------------------------------------
-- SELLER 2: Peps Mattress (id = 2) - Strict Tenant Isolation Benchmark
-- Guardrails: max_bid_cap = 50.00, max_budget_cap = 5000.00, neg_key_max_no_orders = 10
-- Communication: increase_budget_option = 1 (Pre-approved / Autonomous)
-- -----------------------------------------------------------------------------
INSERT INTO `sellers` (`id`, `seller_name`, `seller_type`, `account_id`, `profile_id`, `max_bid_cap`, `max_budget_cap`, `neg_key_max_no_orders`, `activated`, `status`)
VALUES (2, 'Peps Mattress', 'seller', 'A2PEPSMATTRESS', 'PROF_PEPS_002', 50.00, 5000.00, 10, 1, 'active');

INSERT INTO `seller_communication_management` (`id`, `seller_id`, `day_parting_option`, `increase_budget_option`)
VALUES (2, 2, 1, 1);

-- -----------------------------------------------------------------------------
-- CAMPAIGNS FOR SELLER 1 (Navla Naturals)
-- -----------------------------------------------------------------------------
-- Campaign 1: O3M-SP-AT-MAIN (Candidate for Tier 3 Out-Of-Budget +30% Scaling)
-- Spend: 460.00 / 500.00 = 92% utilization (>80%), ROAS: 4.20
INSERT INTO `campaigns` (`id`, `seller_id`, `campaign_name`, `campaign_str_id`, `campaign_type`, `targeting_type`, `state`, `budget_type`, `budget`, `status`)
VALUES (101, 1, 'O3M-SP-AT-MAIN', 'CAMP101', 'sp', 'auto', 'enabled', 'daily', 500.00, 'active');

INSERT INTO `campaign_optimizers` (`id`, `seller_id`, `campaign_id`, `campaign_str_id`, `dnt`, `daily_budget`, `budget_rule`, `target_acos`, `neg_term_opt`, `neg_key_max_no_orders`)
VALUES (101, 1, 101, 'CAMP101', 0, 500.00, 'aggressive_scale', 25.00, 1, 8);

INSERT INTO `campaign_metrics` (`id`, `campaign_id`, `seller_id`, `campaign_str_id`, `campaign_status`, `campaign_budget`, `status_date`, `impressions`, `clicks`, `spend`, `acos`, `orders`, `sales`, `roas`)
VALUES 
(1001, 101, 1, 'CAMP101', 'enabled', 500.00, '2026-11-24', 16500, 540, 410.00, 24.12, 32, 1700.00, 4.15),
(1002, 101, 1, 'CAMP101', 'enabled', 500.00, '2026-11-25', 18500, 620, 460.00, 23.81, 38, 1932.00, 4.20);

-- Campaign 2: O3M-SP-ML-EXACT (Tier 1 Neg Harvesting & Tier 2 Bid Optimization)
INSERT INTO `campaigns` (`id`, `seller_id`, `campaign_name`, `campaign_str_id`, `campaign_type`, `targeting_type`, `state`, `budget_type`, `budget`, `status`)
VALUES (102, 1, 'O3M-SP-ML-EXACT', 'CAMP102', 'sp', 'manual', 'enabled', 'daily', 400.00, 'active');

INSERT INTO `campaign_optimizers` (`id`, `seller_id`, `campaign_id`, `campaign_str_id`, `dnt`, `daily_budget`, `budget_rule`, `target_acos`, `neg_term_opt`, `neg_key_max_no_orders`)
VALUES (102, 1, 102, 'CAMP102', 0, 400.00, 'target_acos_opt', 25.00, 1, 8);

INSERT INTO `campaign_metrics` (`id`, `campaign_id`, `seller_id`, `campaign_str_id`, `campaign_status`, `campaign_budget`, `status_date`, `impressions`, `clicks`, `spend`, `acos`, `orders`, `sales`, `roas`)
VALUES 
(1003, 102, 1, 'CAMP102', 'enabled', 400.00, '2026-11-24', 11200, 290, 260.00, 22.61, 21, 1150.00, 4.42),
(1004, 102, 1, 'CAMP102', 'enabled', 400.00, '2026-11-25', 12000, 310, 280.00, 21.54, 24, 1300.00, 4.64);

-- Campaign 3: O3M-SP-BRAND-PROTECT (Do Not Touch Guardrail Test Case)
INSERT INTO `campaigns` (`id`, `seller_id`, `campaign_name`, `campaign_str_id`, `campaign_type`, `targeting_type`, `state`, `budget_type`, `budget`, `status`)
VALUES (103, 1, 'O3M-SP-BRAND-PROTECT', 'CAMP103', 'sp', 'manual', 'enabled', 'daily', 300.00, 'active');

INSERT INTO `campaign_optimizers` (`id`, `seller_id`, `campaign_id`, `campaign_str_id`, `dnt`, `daily_budget`, `budget_rule`, `target_acos`, `neg_term_opt`, `neg_key_max_no_orders`)
VALUES (103, 1, 103, 'CAMP103', 1, 300.00, 'brand_guard', 15.00, 0, 10);

INSERT INTO `campaign_metrics` (`id`, `campaign_id`, `seller_id`, `campaign_str_id`, `campaign_status`, `campaign_budget`, `status_date`, `impressions`, `clicks`, `spend`, `acos`, `orders`, `sales`, `roas`)
VALUES 
(1005, 103, 1, 'CAMP103', 'enabled', 300.00, '2026-11-25', 8000, 150, 120.00, 10.00, 22, 1200.00, 10.00);

-- -----------------------------------------------------------------------------
-- CAMPAIGNS FOR SELLER 2 (Peps Mattress)
-- -----------------------------------------------------------------------------
INSERT INTO `campaigns` (`id`, `seller_id`, `campaign_name`, `campaign_str_id`, `campaign_type`, `targeting_type`, `state`, `budget_type`, `budget`, `status`)
VALUES (201, 2, 'PEPS-SP-ORTHO-MATTRESS', 'CAMP201', 'sp', 'manual', 'enabled', 'daily', 1200.00, 'active');

INSERT INTO `campaign_optimizers` (`id`, `seller_id`, `campaign_id`, `campaign_str_id`, `dnt`, `daily_budget`, `budget_rule`, `target_acos`, `neg_term_opt`, `neg_key_max_no_orders`)
VALUES (201, 2, 201, 'CAMP201', 0, 1200.00, 'standard_scale', 20.00, 1, 10);

INSERT INTO `campaign_metrics` (`id`, `campaign_id`, `seller_id`, `campaign_str_id`, `campaign_status`, `campaign_budget`, `status_date`, `impressions`, `clicks`, `spend`, `acos`, `orders`, `sales`, `roas`)
VALUES (2001, 201, 2, 'CAMP201', 'enabled', 1200.00, '2026-11-25', 25000, 400, 750.00, 18.75, 10, 4000.00, 5.33);

-- -----------------------------------------------------------------------------
-- KEYWORD REPORTS (For Navla Naturals & Peps Mattress)
-- -----------------------------------------------------------------------------
-- High-ROAS winner keyword ready for Tier 2 bid scale in CAMP102
INSERT INTO `keyword_reports` (`id`, `seller_id`, `campaign_str_id`, `ad_group_id`, `keyword_id`, `keyword_text`, `match_type`, `state`, `bid`, `status_date`, `impressions`, `clicks`, `spend`, `acos`, `orders`, `sales`, `roas`)
VALUES 
(501, 1, 'CAMP102', 'AG102_1', 'KW102_01', 'natural organic hair oil', 'exact', 'enabled', 1.40, '2026-11-25', 4500, 120, 115.00, 14.38, 18, 800.00, 6.96),
(502, 1, 'CAMP102', 'AG102_1', 'KW102_02', 'ayurvedic hair regrowth oil', 'exact', 'enabled', 1.80, '2026-11-25', 3800, 95, 98.00, 28.00, 7, 350.00, 3.57),
(503, 1, 'CAMP103', 'AG103_1', 'KW103_01', 'navla naturals pure almond oil', 'exact', 'enabled', 0.85, '2026-11-25', 8000, 150, 120.00, 10.00, 22, 1200.00, 10.00),
(504, 2, 'CAMP201', 'AG201_1', 'KW201_01', 'orthopedic memory foam mattress king', 'exact', 'enabled', 3.20, '2026-11-25', 18000, 310, 580.00, 18.13, 8, 3200.00, 5.52);

-- -----------------------------------------------------------------------------
-- SEARCH TERMS (Testing Tier 1 Bleeders for Negative Keyword Harvesting)
-- -----------------------------------------------------------------------------
-- High-spend, zero-order search terms in CAMP102 (Seller 1 has neg_key_max_no_orders = 8)
INSERT INTO `search_terms` (`id`, `seller_id`, `date`, `campaign_id`, `adgroup_id`, `keyword_id`, `campaign_name`, `adgroup_name`, `keyword`, `match_type`, `search_term`, `impressions`, `clicks`, `cost`, `sales_7d`, `units_sold_clicks_7d`)
VALUES 
-- Bleeder search term 1: 14 clicks (> 8 threshold), $42.00 spend, 0 orders
(801, 1, '2026-11-25', 102, 'AG102_1', 'KW102_02', 'O3M-SP-ML-EXACT', 'Hair Growth AG', 'ayurvedic hair regrowth oil', 'phrase', 'organic aloe vera gel 500ml fake', 820, 14, 42.00, 0.00, 0),
-- Bleeder search term 2: 11 clicks (> 8 threshold), $33.50 spend, 0 orders
(802, 1, '2026-11-25', 102, 'AG102_1', 'KW102_02', 'O3M-SP-ML-EXACT', 'Hair Growth AG', 'ayurvedic hair regrowth oil', 'phrase', 'cheap chemical shampoo bulk', 650, 11, 33.50, 0.00, 0),
-- High-converting search term: 45 clicks, $54.00 cost, $480 sales, 11 orders
(803, 1, '2026-11-25', 102, 'AG102_1', 'KW102_01', 'O3M-SP-ML-EXACT', 'Hair Growth AG', 'natural organic hair oil', 'exact', 'natural organic hair oil', 2100, 45, 54.00, 480.00, 11),
-- Tenant 2 search term
(804, 2, '2026-11-25', 201, 'AG201_1', 'KW201_01', 'PEPS-SP-ORTHO-MATTRESS', 'Mattress AG', 'orthopedic memory foam mattress king', 'exact', 'orthopedic memory foam mattress king size', 3400, 65, 140.00, 800.00, 2);

-- -----------------------------------------------------------------------------
-- ADACE STATUS LOGS (Historical Execution & Audit Trail)
-- -----------------------------------------------------------------------------
INSERT INTO `adace_status_logs` (`id`, `run_date`, `seller_id`, `module_id`, `action_id`, `status_text`, `rule`, `campaign_str_id`, `campaign_prv_budget`, `campaign_cur_budget`, `ad_grp_prev_bid`, `ad_grp_cur_bid`, `keywd_prev_bid`, `keywd_cur_bid`, `neg_keywd_product`, `impressions`, `clicks`, `cpc`, `cost`, `orders`)
VALUES 
(1, '2026-11-24 08:30:00', 1, 3, 10, 'Initialized Campaign Baseline Optimizer', 'BASELINE_INIT', 'CAMP101', 500.00, 500.00, NULL, NULL, NULL, NULL, NULL, 16500, 540, 0.76, 410.00, 32),
(2, '2026-11-24 09:15:00', 1, 1, 2, 'Identified search terms candidate for negative exact check', 'NEG_KEYWORD_SCAN', 'CAMP102', 400.00, 400.00, NULL, NULL, NULL, NULL, NULL, 11200, 290, 0.90, 260.00, 21),
(3, '2026-11-25 08:00:00', 2, 3, 10, 'Tenant Peps Mattress Baseline Initialized', 'BASELINE_INIT', 'CAMP201', 1200.00, 1200.00, NULL, NULL, NULL, NULL, NULL, 25000, 400, 1.88, 750.00, 10);
