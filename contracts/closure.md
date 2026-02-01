```scala
{{
    // Constants
  val CollateralContractScript = fromBase58("5b1fi29V1anTDfdYDkgLErXeHZH3yafCFMmiMWEQyVpG")
  val InterestNFT = fromBase58("9EaU5tpXRb4vxmgSu6zfbUc8Vurt9JzcU1BXXVUibt47")
  val RepaymentContractScript = fromBase58("FGpcu5PhtajjL5UCz78NpHTt6GVXZehmEc1rTc5gnPTz")
    val BorrowTokenDenomination = 10000000000000000L.toBigInt
    val LiquidationThresholdDenom = 1000L
    val MinimumTransactionFee = 1100000L
    val ProportionDenom = 1000L
    val feeDenom = 1000

    // Current box (the NFT control box)
    val currentScript = SELF.propositionBytes
    val currentValue = SELF.value
    val currentTokens = SELF.tokens
    val currentNFT = SELF.tokens(0)
    
    // Registers store loan control parameters
    // R4: User's proposition bytes (borrower address)
    // R5: User's public key (GroupElement) for signature verification
    // R6: Liquidation threshold (Long) - e.g., 1200 means 120% health required
    val userAddress = SELF.R4[Coll[Byte]].get
    val userPk = SELF.R5[GroupElement].get
    val quoteNftId = SELF.R7[Coll[Byte]].get
	val specialBytes = SELF.R9[Coll[Byte]].get
	val settings = SELF.R6[Coll[Long]].get
	val liquidationThreshold = settings(0)
	val feeAllowance = settings(1)
	val heightSpend = settings(2)

    // Find successor box - NFT is ALWAYS recreated
    val successor = OUTPUTS.filter{{
        (b: Box) => b.tokens.size > 0 && b.tokens(0) == currentNFT
    }}.getOrElse(0, SELF)
    
    // Self-preservation conditions (ALWAYS required)
    val scriptRetained = successor.propositionBytes == currentScript
    val valueRetained = successor.value >= currentValue - MinimumTransactionFee
    val tokensRetained = successor.tokens == currentTokens
    val registersRetained = (
        successor.R4[Coll[Byte]].get == userAddress &&
        successor.R5[GroupElement].get == userPk &&
        successor.R6[Coll[Long]].get == settings &&
        successor.R7[Coll[Byte]].get == quoteNftId &&
		successor.R9[Coll[Byte]].get == specialBytes
		)
    
    val selfPreserved = (
        scriptRetained &&
        valueRetained &&
        tokensRetained &&
        registersRetained &&
		successor.id != SELF.id
    )

    // === SPENDING PATHS ===
    
    // Path 1: Liquidation - allowed when loan health is below threshold
    val collateralBoxes = INPUTS.filter{{
        (b: Box) => blake2b256(b.propositionBytes) == CollateralContractScript
    }}
    
    val isValidLiquidation = if (collateralBoxes.size > 0) {{
        val collateralBox = collateralBoxes(0)
        
        // Get quote NFT ID from collateral box R7
        
        // Find quote box in OUTPUTS
        val quoteBox = OUTPUTS.filter{{
            (b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == quoteNftId
        }}(0)
        
        // Get collateral value from quote box
        // R4[Coll[Long]]: (0) borrowLimit, (1) quotePrice, (2) threshold, (3) penalty, ...
        val quoteReport = quoteBox.R4[Coll[Long]].get
        val quotePriceRaw = quoteReport(1).toBigInt  // Collateral value in pool currency
        val quotePrice = quotePriceRaw - quotePriceRaw * feeAllowance / feeDenom
        // Get borrow tokens from collateral box
        val borrowTokens = collateralBox.tokens(0)._2
        val borrowTokenId = collateralBox.tokens(0)._1
        
        // Get interest box for current borrow token value
        val interestBox = CONTEXT.dataInputs.filter{{
            (b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == InterestNFT
        }}(0)
        val borrowTokenValue = interestBox.R5[BigInt].get
        
        // Calculate total debt in native currency
        val totalDebt = borrowTokens.toBigInt * borrowTokenValue / BorrowTokenDenomination
        
        // Calculate loan health: (quotePrice * 1000) / totalDebt
        val loanHealth = (quotePrice * LiquidationThresholdDenom.toBigInt) / totalDebt

        // Loan is unhealthy if health < threshold
        val isUnhealthy = loanHealth < liquidationThreshold.toBigInt || HEIGHT >= heightSpend
        
        // === Verify repayment box is created with all borrow tokens ===
        val repaymentBoxes = OUTPUTS.filter{{
            (b: Box) => blake2b256(b.propositionBytes) == RepaymentContractScript
        }}
        
        val validRepayment = if (repaymentBoxes.size > 0) {{
            val repaymentBox = repaymentBoxes(0)
            val repaymentBorrowTokens = repaymentBox.tokens(0)
            // All borrow tokens must go to repayment box
            repaymentBorrowTokens._1 == borrowTokenId && 
            repaymentBorrowTokens._2 == borrowTokens
        }} else {{
            false
        }}
        
        // === Calculate and verify leftover collateral to user ===
        // Proportion to user = (quotePrice - totalDebt) / quotePrice
        // User should receive at least this proportion of each collateral asset
        
        val userBoxes = OUTPUTS.filter{{
            (b: Box) => b.propositionBytes == userAddress
        }}
        
        val validUserShare = if (userBoxes.size > 0 && quotePrice > totalDebt) {{
            val userBox = userBoxes(0)
            
            // Calculate user's proportion (scaled by ProportionDenom to avoid fractions)
            // userProportion = (quotePrice - totalDebt) * 1000 / quotePrice
            val userProportion = ((quotePrice - totalDebt) * ProportionDenom.toBigInt) / quotePrice
            
            // Collateral tokens are at index 1+ in collateral box (index 0 is borrow tokens)
            val collateralTokens = collateralBox.tokens.slice(1, collateralBox.tokens.size)
            
            // Check ERG: user should get at least proportional ERG minus tx fee
            val collateralErg = collateralBox.value
            val minUserErg = (collateralErg.toBigInt * userProportion / ProportionDenom.toBigInt) - MinimumTransactionFee.toBigInt
            val validUserErg = userBox.value.toBigInt >= minUserErg
            
            // User box tokens must match collateral tokens in same order
            // Assumes user box contains exactly the collateral tokens in the same order
            val userTokens = userBox.tokens
            
            // Must have same number of tokens
            val sameTokenCount = userTokens.size == collateralTokens.size
            
            // Zip and validate: same token IDs and sufficient amounts
            val tokenPairs = collateralTokens.zip(userTokens)
            val validUserTokens = tokenPairs.forall{{
                (pair: ((Coll[Byte], Long), (Coll[Byte], Long))) =>
                val collateralToken = pair._1
                val userToken = pair._2
                
                val tokenId = collateralToken._1
                val collateralAmount = collateralToken._2
                val minUserAmount = (collateralAmount.toBigInt * userProportion) / ProportionDenom.toBigInt
                
                // Token ID must match (same ordering assumed)
                val sameTokenId = userToken._1 == tokenId
                // Amount must be at least the proportional share
                val sufficientAmount = userToken._2.toBigInt >= minUserAmount
                
                sameTokenId && sufficientAmount
            }}
            
            validUserErg && sameTokenCount && validUserTokens
        }} else if (quotePrice <= totalDebt) {{
            // No leftover - debt equals or exceeds collateral value
            // User gets nothing, which is valid
            true
        }} else {{
            false
        }}
        
        isUnhealthy && validRepayment && validUserShare
    }} else {{
        false
    }}
    
    // Path 2: User signature - owner can always spend
    val userAuthorized = proveDlog(userPk)

    // Final: Self-preservation AND (liquidation conditions OR user signature)
    userAuthorized || (sigmaProp(selfPreserved) && sigmaProp(isValidLiquidation))
}}
```