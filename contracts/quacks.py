from helpers.node_calls import compile_script


def generate_pool_script(collateralContractScript, childBoxNft, parameterBoxNft, serviceFeeThresholds):
    return compile_script(f'''{{
	// Constants
	val InterestNFT = fromBase58("{childBoxNft}")
	val ParamaterBoxNft = fromBase58("{parameterBoxNft}")
	val CollateralContractScript = fromBase58("{collateralContractScript}")

	val MaxLendTokens = 9000000000000010L // Set 1,000,000 higher than true maximum so that genesis lend token value is 1.
	val MaxBorrowTokens = 9000000000000000L
	val BorrowTokenDenomination = 10000000000000000L.toBigInt
	val MinimumBoxValue = 1000000
	val LendTokenMultipler = 1000000000000000L.toBigInt
	val LiquidationThresholdDenomination = 1000

	// Current pool values
	val currentScript = SELF.propositionBytes
	val currentPoolValue = SELF.value
	val currentPoolNft = SELF.tokens(0)
	val currentLendTokens = SELF.tokens(1)
	val currentBorrowTokens = SELF.tokens(2)
	val currentPooledTokens = SELF.tokens(3)
	val currentLendTokensCirculating = MaxLendTokens - currentLendTokens._2
	val currentBorrowTokensCirculating = MaxBorrowTokens - currentBorrowTokens._2
	val currentPooledAssets = currentPooledTokens._2	

	// Successor pool values
	val successor = OUTPUTS.filter{{
		(out : Box) => out.tokens.size > 0 && out.tokens(0) == currentPoolNft
	}}(0)
	val successorScript = successor.propositionBytes
	val successorPoolValue = successor.value
	val successorPoolNft = successor.tokens(0)
	val successorLendTokens = successor.tokens(1)
	val successorBorrowTokens = successor.tokens(2)
	val successorPooledTokens = successor.tokens(3)
	val successorLendTokensCirculating = MaxLendTokens - successorLendTokens._2
	val successorBorrowTokensCirculating = MaxBorrowTokens - successorBorrowTokens._2
	val successorPooledAssets = successorPooledTokens._2

	// Validation conditions under all spending paths
	val commonConditions = (
		successorScript == currentScript && 
		successorLendTokens._1 == currentLendTokens._1 &&
		successorBorrowTokens._1 == currentBorrowTokens._1 &&
		successorPoolValue >= MinimumBoxValue &&
		successorPooledTokens._1 == currentPooledTokens._1
	)
	
	// Extract Values from Interest Box
	val interestBox = CONTEXT.dataInputs.filter{{
		(b : Box) => b.tokens.size > 0 && b.tokens(0)._1 == InterestNFT
	}}(0)
	val interestBoxNFT = interestBox.tokens(0)._1
	val borrowTokenValue = interestBox.R5[BigInt].get
	val currentBorrowed = currentBorrowTokensCirculating.toBigInt * borrowTokenValue / 	BorrowTokenDenomination
	val successorBorrowed = successorBorrowTokensCirculating.toBigInt * borrowTokenValue / BorrowTokenDenomination
	
	// Extract values form poolSettings
	val poolSettings = CONTEXT.dataInputs.filter{{
		(b : Box) => b.tokens.size > 0 && b.tokens(0)._1 == ParamaterBoxNft
	}}(0)
	val serviceParamNft = poolSettings.tokens(0)
	val customLogicNFTs = poolSettings.R4[Coll[Coll[Byte]]].get
	val paramServiceFeeScript = poolSettings.R5[Coll[Byte]].get
	val feeSettings = poolSettings.R6[Coll[Long]].get
	val scriptSettings = poolSettings.R7[Coll[Long]].get

	// Calculate Lend Token valuation
	val currentLendTokenValue = LendTokenMultipler * (currentPooledAssets.toBigInt + currentBorrowed.toBigInt) / currentLendTokensCirculating.toBigInt
	val successorLendTokenValue = LendTokenMultipler * (successorPooledAssets.toBigInt + successorBorrowed.toBigInt) / successorLendTokensCirculating.toBigInt

	// Additional validation conditions specific to exchange operation
	val isLendTokenValueMaintained = successorLendTokenValue > currentLendTokenValue // Ensures the current value of an LP token has not decreased
	val isBorrowTokensUnchanged = successorBorrowTokens == currentBorrowTokens
	
	// Useful value to store
	val deltaAssetsInPool = successorPooledAssets - currentPooledAssets
	val absDeltaAssetsInPool = if (deltaAssetsInPool > 0) deltaAssetsInPool else deltaAssetsInPool * -1
	
	val plausibleServiceFeeBoxes = OUTPUTS.filter{{
		(out: Box) => out.propositionBytes == paramServiceFeeScript
	}}	
	
	// Validate service fee
	val isValidServiceFee = if (plausibleServiceFeeBoxes.size > 0) {{
		// Extract values from service fee box
		val serviceFeeBox = plausibleServiceFeeBoxes(0)
		val serviceFeeScript = serviceFeeBox.propositionBytes
		val serviceFeeValue = serviceFeeBox.value
		val serviceFeeTokens = serviceFeeBox.tokens(0)
		val serviceFeeAssets = serviceFeeTokens._2
		
		val sFeeStepOne = feeSettings(0)
		val sFeeStepTwo = feeSettings(1)
		val sFeeDivisorOne = feeSettings(2)
		val sFeeDivisorTwo = feeSettings(3)
		val sFeeDivisorThree = feeSettings(4)
		
		// Calculate total service fee owed
		val totalServiceFee = if (absDeltaAssetsInPool <= sFeeStepOne) {{
			absDeltaAssetsInPool / sFeeDivisorOne
		}} else {{
			if (absDeltaAssetsInPool <= sFeeStepTwo) {{
				(absDeltaAssetsInPool - sFeeStepOne) / sFeeDivisorTwo +
				sFeeStepOne / sFeeDivisorOne
			}} else {{
				(absDeltaAssetsInPool - sFeeStepTwo - sFeeStepOne) / sFeeDivisorThree +
				sFeeStepTwo / sFeeDivisorTwo +
				sFeeStepOne / sFeeDivisorOne
			}}
		}}
			
		// Validate service fee box
		val validServiceScript = serviceFeeScript == paramServiceFeeScript
		val validServiceFeeValue = serviceFeeValue >= MinimumBoxValue
		val validServiceTokens = serviceFeeAssets >= max(totalServiceFee, 1L) && serviceFeeTokens._1 == currentPooledTokens._1
	
		
		// Apply validation conditions
		(
			validServiceScript &&
			validServiceFeeValue &&
			validServiceTokens
		)
	}} else {{
		false
	}}

	// Validate exchange operation
	val isValidExchange = (
		commonConditions &&
		isBorrowTokensUnchanged &&
		isLendTokenValueMaintained &&
		isValidServiceFee
	)

	// Allow for deposits
	val deltaTotalBorrowed = successorBorrowTokensCirculating - currentBorrowTokensCirculating
	val deltaReservedLendTokens = successorLendTokens._2 - currentLendTokens._2

	val isLendTokensUnchanged = successorLendTokens == currentLendTokens
	val isAssetsInPoolIncreasing = deltaAssetsInPool > 0
	val isDepositDeltaBorrowedValid = deltaTotalBorrowed < 0 // Enforces a deposit to add borrow tokens to the pool

	// Validate deposit operation
	val isValidDeposit = (
		commonConditions &&
		isLendTokensUnchanged &&
		isAssetsInPoolIncreasing &&
		isDepositDeltaBorrowedValid
	)
	
	val plausibleCollateralBoxes = OUTPUTS.filter{{
		(b: Box) => blake2b256(b.propositionBytes) == CollateralContractScript
	}}
	
	val isValidBorrow = if (plausibleCollateralBoxes.size > 0) {{
		val collateralBox = plausibleCollateralBoxes(0)
		val collateralValue = collateralBox.value
		val collateralBorrowTokens = collateralBox.tokens(0)
		val collateralBorrower = collateralBox.R4[Coll[Byte]].get
		val collateralUserPk = collateralBox.R5[GroupElement].get
		val collateralSettings = collateralBox.R6[Coll[Long]].get // (Forced Liquidation, Buffer, Threshold...)
		val forcedLiquidation = collateralSettings(0)
		val bufferLiquidation = collateralSettings(1)
		val threshold = collateralSettings(2)
		val collateralQuoteNFT = collateralBox.R7[Coll[Byte]].get
		val loanAmount = collateralBorrowTokens._2.toBigInt * borrowTokenValue / BorrowTokenDenomination
	
		val fQuote = OUTPUTS.filter{{
		(b: Box) => b.tokens.size > 0 && customLogicNFTs.exists{{
			(NFT: Coll[Byte]) => b.tokens(0)._1 == NFT && NFT == collateralQuoteNFT
			}}
		}}(0)
		val quotePrice = fQuote.R4[Long].get
		val quoteSettings = fQuote.R6[Coll[Long]].get 
		
		val isCorrectCollateralAmount = quotePrice >= loanAmount.toBigInt * threshold.toBigInt / LiquidationThresholdDenomination.toBigInt
		val isCorrectCollateralSettings = collateralSettings.slice(0, quoteSettings.size) == quoteSettings
		
		val isCollateralTokensPreserved = collateralBorrowTokens._2 + currentBorrowTokens._2 == successorBorrowTokens._2
		
		val isAssetsInPoolDecreasing = deltaAssetsInPool < 0
		val isAssetAmountValid = deltaAssetsInPool * -1 == loanAmount
		val isTotalBorrowedValid = deltaTotalBorrowed == collateralBorrowTokens._2

		(
			commonConditions &&
			successorLendTokens == currentLendTokens &&
			isAssetsInPoolDecreasing &&
			isAssetAmountValid &&
			isTotalBorrowedValid &&
			isCorrectCollateralSettings &&
			isCorrectCollateralAmount
			)	
	}} else {{
		false
	}}
	sigmaProp(isValidExchange || isValidDeposit || isValidBorrow)	
}}''')


def generate_collateral_script(repaymentScript, interestNft, poolCurrencyId):
	return compile_script(f'''{{	
	// * Implicit Conditions
	// Constants
	val RepaymentContractScript = fromBase58("{repaymentScript}")
	val InterestNFT = fromBase58("{interestNft}")
	val PoolCurrencyId = fromBase58("{poolCurrencyId}")
	val BorrowTokenDenomination = 10000000000000000L.toBigInt
	val InterestRateDenom = 100000000L
	val MaximumNetworkFee = 5000000
	val DexLpTaxDenomination = 1000 
	val LiquidationThresholdDenom = 1000
	val PenaltyDenom = 1000
	val MinimumTransactionFee = 1000000L
	val MinimumBoxValue = 1000000
	val Slippage = 2 // Divided by 100 to represent 2%
	val defaultBuffer = 100000000L

	// Current Collateral Box
	val currentScript = SELF.propositionBytes
	val currentValue = SELF.value
	val currentBorrowTokens = SELF.tokens(0)
	val currentBorrower = SELF.R4[Coll[Byte]].get
	val currentUserPk = SELF.R5[GroupElement].get
	val currentSettings = SELF.R6[Coll[Long]].get // (Forced Liquidation, Buffer, iThreshold, Penalty, Automated Actions, More....)
	val iForcedLiquidation = currentSettings(0)
	val iBufferLiquidation = currentSettings(1)
	val iThreshold = currentSettings(2)
	val iPenalty = currentSettings(3)
	val iAutomatedThreshold = currentSettings(4)
	val iAutomatedPercentrage = currentSettings(5)
	val iPersistAutomatedAction = currentSettings(6)
	val currentQuoteNFT = SELF.R7[Coll[Byte]].get
	val loanAmount = currentBorrowTokens._2
	
	// Extract values from interest box
	val interestBox = CONTEXT.dataInputs(0)
	val interestBoxNFT = interestBox.tokens(0)._1
	val isValidInterestBox = interestBoxNFT == InterestNFT
	val borrowTokenValue = interestBox.R5[BigInt].get

	val totalOwed = loanAmount.toBigInt * borrowTokenValue / BorrowTokenDenomination
	
	// Fetch Collateral Quote Box
	val fQuotes = OUTPUTS.filter{{
		(b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == currentQuoteNFT
	}}
	
	if (fQuotes.size > 0) {{
		val fQuote = fQuotes.getOrElse(0, SELF)
		val quotePrice = fQuote.R4[Long].get
		val quotePriceSecondary = fQuote.R5[Long].get
		
		val fCollaterals = OUTPUTS.filter{{
			(b: Box) => b.propositionBytes == SELF.propositionBytes
		}}
		
		val fRepayments = OUTPUTS.filter{{
			(b: Box) => blake2b256(b.propositionBytes) == RepaymentContractScript
		}}
		
		if (fCollaterals.size > 0) {{
			val fCollateral = fCollaterals.getOrElse(0, SELF)
		
			val fCollateralValue = fCollateral.value
			val fCollateralBorrowTokens = fCollateral.tokens(0)
			val fCollateralBorrower = fCollateral.R4[Coll[Byte]].get
			val fCollateralUserPk = fCollateral.R5[GroupElement].get
			val fCollateralSettings = fCollateral.R6[Coll[Long]].get
			val fForcedLiquidation = fCollateralSettings(0)
			val fBufferLiquidation = fCollateralSettings(1)
			val fThreshold = fCollateralSettings(2)
			val fPenalty = fCollateralSettings(3)
			val fAutomatedThreshold = fCollateralSettings(4)
			val fAutomatedPercentrage = fCollateralSettings(5)
			val fPersistAutomatedAction = currentSettings(6)
			val fCollateralQuoteNFT = fCollateral.R7[Coll[Byte]].get

			val fCollateralCommon = (
				fCollateralBorrowTokens._1 == currentBorrowTokens._1 &&
				fCollateralBorrower == currentBorrower &&
				fCollateralUserPk == currentUserPk &&
				fCollateralQuoteNFT == currentQuoteNFT
			)
			if (fRepayments.size > 0) {{
				// Partial Repay and Automated Actions
				val fRepayment = fRepayments.getOrElse(0, SELF)		
				
				
				val fRepaymentValue = fRepayment.value
				val fRepaymentBorrowTokens = fRepayment.tokens(0)
				val fRepaymentLoanTokens = fRepayment.tokens(1)
				val repaymentMade = fRepaymentLoanTokens._2
				
				val expectedBorrowTokens = currentBorrowTokens._2.toBigInt - (repaymentMade.toBigInt * BorrowTokenDenomination.toBigInt / borrowTokenValue.toBigInt)
				val validBorrowTokens = fCollateralBorrowTokens._2.toBigInt >= expectedBorrowTokens
				
				val fRepaymentCommon = (
					fRepaymentValue >= MinimumBoxValue + MinimumTransactionFee &&
					fRepaymentBorrowTokens._1 == currentBorrowTokens._1 &&
					fRepaymentLoanTokens._1 == PoolCurrencyId
				)	
				
				// Specific Partial Repay Conditions				
				val finalTotalOwed = fCollateralBorrowTokens._2 * borrowTokenValue / BorrowTokenDenomination
				val isSufficientCollateral = quotePrice >= finalTotalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt
				
				val partialRepayment = sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					fCollateralValue >= currentValue &&
					validBorrowTokens &&
					fCollateralSettings == currentSettings &&
					// Complete Repayment Checks (Borrow Token Amount, Loan Token Amount*)
					fRepaymentCommon &&
					fRepaymentBorrowTokens._2 == currentBorrowTokens._2 - fCollateralBorrowTokens._2 &&
					isValidInterestBox &&
					isSufficientCollateral
				)
				
				val actionsAllowed = iPersistAutomatedAction > 0
				val isBelowAutomatedThreshold = quotePrice <= totalOwed.toBigInt * iAutomatedThreshold.toBigInt / LiquidationThresholdDenom.toBigInt 
				val cannotLiquidate = quotePrice <= totalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt
				val isFinalCollateralValid = fCollateralValue.toBigInt + MaximumNetworkFee >= currentValue.toBigInt * fAutomatedPercentrage.toBigInt / LiquidationThresholdDenom.toBigInt
				val isValidRepaymentAmount = repaymentMade >= quotePriceSecondary

				val automatedActions = sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					isFinalCollateralValid &&
					validBorrowTokens &&
					fCollateralSettings.slice(0,6) == currentSettings.slice(0,6) &&
					fPersistAutomatedAction == iPersistAutomatedAction - 1 &&
					// Complete Repayment Checks (Borrow Token Amount, Loan Token Amount*)
					fRepaymentCommon &&
					fRepaymentBorrowTokens._2 == currentBorrowTokens._2 - fCollateralBorrowTokens._2 &&
					isValidRepaymentAmount &&
					isValidInterestBox &&
					actionsAllowed &&
					isBelowAutomatedThreshold && 
					cannotLiquidate &&
					isFinalCollateralValid
				)
				
				// Specific Automated Action Conditions
				partialRepayment || automatedActions
			}} else {{
				// Prep Liquidation and Adjust Collateteral
				// Specific Ready to liquidate conditions
				val adjustBuffer = fBufferLiquidation > HEIGHT && fBufferLiquidation < HEIGHT + 5
				val finalTotalOwed = fCollateralBorrowTokens._2 * borrowTokenValue / BorrowTokenDenomination
				val isSufficientCollateral = quotePrice >= finalTotalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt
				
				val readyToLiquidate = sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					fCollateralValue >= currentValue - MinimumTransactionFee &&
					fCollateral.tokens == SELF.tokens &&
					fForcedLiquidation == iForcedLiquidation &&
					fBufferLiquidation > HEIGHT && fBufferLiquidation < HEIGHT + 5 &&
					fThreshold == iThreshold &&
					fPenalty == iPenalty &&
					fAutomatedPercentrage == iAutomatedPercentrage &&
					fAutomatedThreshold == iAutomatedThreshold &&
					fPersistAutomatedAction == iPersistAutomatedAction &&
					!isSufficientCollateral &&
					isValidInterestBox					
				)
				
				
				val isValidCollateral = quotePrice >= totalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt

				val adjustCollateral = proveDlog(currentUserPk) && 
				sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					fCollateralValue >= 3 * MinimumBoxValue + MinimumTransactionFee &&
					isValidCollateral &&
					fCollateral.tokens == SELF.tokens &&
					fCollateralSettings == currentSettings &&
					isValidInterestBox
				)
				readyToLiquidate || adjustCollateral
			}}
			
		}} else {{
			val fRepayment = fRepayments.getOrElse(0, SELF)
				
			val fRepaymentValue = fRepayment.value
			val fRepaymentBorrowTokens = fRepayment.tokens(0)
			val fRepaymentLoanTokens = fRepayment.tokens(1)
			val repaymentMade = fRepaymentLoanTokens._2
			
			val fRepaymentCommon = (
				fRepaymentValue >= MinimumBoxValue + MinimumTransactionFee &&
				fRepaymentBorrowTokens._1 == currentBorrowTokens._1 &&
				fRepaymentLoanTokens._1 == PoolCurrencyId
			)	
		
			val liquidationAllowed = (
				(
					quotePrice <= totalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt &&
					HEIGHT >= iBufferLiquidation
				) || 
				HEIGHT > iForcedLiquidation
			)
			
			val repaymentAmount = fRepaymentLoanTokens._2
			
			// Apply penalty on repayment and borrower share
			val borrowerShare = ((quotePrice - totalOwed.toBigInt) * (PenaltyDenom.toBigInt - iPenalty.toBigInt)) / PenaltyDenom.toBigInt
			val applyPenalty = if (borrowerShare < 1.toBigInt) {{
				repaymentAmount.toBigInt >= quotePrice
			}} else {{
				val validRepayment = repaymentAmount.toBigInt >= totalOwed.toBigInt + ((quotePrice - totalOwed.toBigInt) * iPenalty.toBigInt / PenaltyDenom.toBigInt)
				val borrowBox = OUTPUTS.filter{{
					(b: Box) => b.propositionBytes == currentBorrower
				}}.getOrElse(0, SELF)
				val validBorrowerShare = borrowBox.tokens(0)._2.toBigInt >= borrowerShare
				val validBorrowerShareId = borrowBox.tokens(0)._1 == PoolCurrencyId
				validRepayment && validBorrowerShare && validBorrowerShareId
			}}   
			
			val liquidate = sigmaProp(
				liquidationAllowed &&
				// Complete Repayment Checks (Borrow Token Amount, Loan Token Amount*)
				fRepaymentCommon &&
				fRepaymentBorrowTokens._2 == currentBorrowTokens._2 &&
				applyPenalty &&
				isValidInterestBox
			)
			liquidate
		}}
	}} else {{
		val fRepayment = OUTPUTS.filter{{
			(b: Box) => blake2b256(b.propositionBytes) == RepaymentContractScript
		}}.getOrElse(0, SELF)
				
		val fRepaymentValue = fRepayment.value
		val fRepaymentBorrowTokens = fRepayment.tokens(0)
		val fRepaymentLoanTokens = fRepayment.tokens(1)
		val repaymentMade = fRepaymentLoanTokens._2
		
		val fRepaymentCommon = (
			fRepaymentValue >= MinimumBoxValue + MinimumTransactionFee &&
			fRepaymentBorrowTokens._1 == currentBorrowTokens._1 &&
			fRepaymentLoanTokens._1 == PoolCurrencyId
		)	
		
		// Extract values from borrowerBox
		val borrowBox = OUTPUTS.filter{{
			(b: Box) => b.propositionBytes == currentBorrower
		}}.getOrElse(0, SELF)	
		val borrowerValue = borrowBox.value
		
		val validBorrowerCollateral = borrowerValue >= currentValue - MinimumTransactionFee
		
		val repayment = sigmaProp(
			// Complete Repayment Checks (Borrow Token Amount, Loan Token Amount*)
			fRepaymentCommon &&
			fRepaymentBorrowTokens._2 == currentBorrowTokens._2 &&
			fRepaymentLoanTokens._2 > totalOwed &&
			validBorrowerCollateral &&
			isValidInterestBox
		)
		repayment
	}}
}}''')

def generate_repayment_script(poolNFT):
	p2s = f"""{{
	// Constants
	val transactionFee = 1000000L 
	val MaxBorrowTokens = 9000000000000000L // Maximum allowed borrowable tokens
	val PoolNft = fromBase58("{poolNFT}") // Non-fungible token for the pool

	val initalPool = INPUTS(0)
	val finalPool = OUTPUTS(0)

	// Amount borrowed
	val loanAmount = SELF.tokens(0)._2
	val repaymentTokens = SELF.tokens(1)
	val repaymentAmount = repaymentTokens._2

	// Find change in the pools borrow tokens
	val borrow0 = MaxBorrowTokens - initalPool.tokens(2)._2
	val borrow1 = MaxBorrowTokens - finalPool.tokens(2)._2	
	val deltaBorrowed = borrow0 - borrow1

	val assetsInPool0 = initalPool.tokens(3)._2
	val assetsInPool1 = finalPool.tokens(3)._2
	val deltaPoolAssets = assetsInPool1 - assetsInPool0

	// Check if the pool NFT matches in both initial and final state
	val validFinalPool = finalPool.tokens(0)._1 == PoolNft
	val validInitialPool = initalPool.tokens(0)._1 == PoolNft

	// Calculate the change in the value of the pool
	val deltaValue = finalPool.value - initalPool.value

	// Check if the delta value is greater than or equal to the loan amount minus the transaction fee
	val validValue = deltaValue >= SELF.value - transactionFee
	// Check if the delta between borrowed amounts is equal to the loan amount
	val validBorrowed = deltaBorrowed == loanAmount
	// Check repayment assets go to pull
	val validRepayment = repaymentAmount == deltaPoolAssets && repaymentTokens._1 == initalPool.tokens(3)._1

	// Check that SELF is INPUTS(1) to prevent same box attack
	val multiBoxSpendSafety = INPUTS(1) == SELF

	// Combine all the conditions into a single Sigma proposition
	sigmaProp(
		validFinalPool &&
		validInitialPool &&
		validValue &&
		validRepayment &&
		validBorrowed &&
		multiBoxSpendSafety
	)
}}"""
	return compile_script(p2s)


def generate_interest_script(poolNFT, interestParamNFT):
	return compile_script(f'''{{
	val PoolNft = fromBase58("{poolNFT}")
	val InterestParamaterBoxNft = fromBase58("{interestParamNFT}")
	val InterestDenomination = 100000000L
	val BorrowTokenDenomination = 10000000000000000L
	val CoefficientDenomination = 100000000L
	val InitiallyLockedLP = 9000000000000000L
	val MaximumBorrowTokens = 9000000000000000L
	val MaximumExecutionFee = 2000000
	val updateFrequency = 120

	val successor = OUTPUTS(0)
	val pool = CONTEXT.dataInputs(0)
	val parameterBox = CONTEXT.dataInputs(1)

	val recordedHeight = SELF.R4[Long].get
	val recordedValue = SELF.R5[BigInt].get

	val finalHeight = successor.R4[Long].get
	val finalValue = successor.R5[BigInt].get

	// get coefficients
	val coefficients = parameterBox.R4[Coll[Long]].get
	val a = coefficients(0).toBigInt
	val b = coefficients(1).toBigInt
	val c = coefficients(2).toBigInt
	val d = coefficients(3).toBigInt
	val e = coefficients(4).toBigInt
	val f = coefficients(5).toBigInt

	val isReadyToUpdate = HEIGHT >= recordedHeight 

	val poolAssets = pool.tokens(3)._2
	val validFinalHeight = finalHeight == recordedHeight + updateFrequency

	val borrowTokens = MaximumBorrowTokens - pool.tokens(2)._2
	val borrowed = borrowTokens * recordedValue / BorrowTokenDenomination
	val util = (InterestDenomination.toBigInt * borrowed.toBigInt / (poolAssets.toBigInt + borrowed.toBigInt))

	val D = CoefficientDenomination.toBigInt
	val M = InterestDenomination.toBigInt
	val x = util.toBigInt

	val currentRate = (
		M + (
			a + 
			(b * x) / D + 
			(c * x) / D * x / M +
			(d * x) / D * x / M * x / M +
			(e * x) / D * x / M * x / M * x / M + 
			(f * x) / D * x / M * x / M * x / M * x / M
			)
		) 

	val retainedERG = successor.value >= SELF.value - MaximumExecutionFee
	val preservedInterestNFT = successor.tokens == SELF.tokens

	val validSuccessorScript = SELF.propositionBytes == successor.propositionBytes
	val validValueUpdate = finalValue == recordedValue * currentRate / M

	val validPoolBox = pool.tokens(0)._1 == PoolNft
	val validParameterBox = parameterBox.tokens(0)._1 == InterestParamaterBoxNft


	val isValidDummyRegisters = (
		successor.R6[Boolean].get &&
		successor.R7[Boolean].get &&
		successor.R8[Boolean].get &&
		successor.R9[Boolean].get
	)


	sigmaProp(
		isReadyToUpdate &&
		validSuccessorScript &&
		retainedERG &&
		preservedInterestNFT &&
		validValueUpdate &&
		validFinalHeight &&
		validPoolBox &&
		validParameterBox &&
		isValidDummyRegisters
	)
}}''')


def generate_logic_script(dexNFT):
	return compile_script(f'''{{
	val DexNFT = fromBase58("{dexNFT}")
	val Slippage = 2.toBigInt
	val SlippageDenom = 100.toBigInt
	val DexFeeDenom = 1000.toBigInt
	val MaximumNetworkFee = 5000000

	val dexBox = CONTEXT.dataInputs.filter {{
		(b : Box) => b.tokens.size > 0 && b.tokens(0)._1 == DexNFT
	}}(0)
	val xAssets = dexBox.value.toBigInt
	val yAssets = dexBox.tokens(2)._2.toBigInt

	val outLogic = OUTPUTS.filter {{
		(b : Box) => b.tokens.size > 0 && b.tokens(0) == SELF.tokens(0)
	}}(0)

	val boxIndex = outLogic.R7[Int].get
	val isIndexOutput = outLogic.R8[Boolean].get
	val boxToQuote = if (isIndexOutput) {{
		OUTPUTS(boxIndex)
	}} else {{
		INPUTS(boxIndex)
	}}		

	val inputAmount = boxToQuote.value.toBigInt - MaximumNetworkFee.toBigInt 
	val dexFee = dexBox.R4[Int].get.toBigInt
	val quotePrice = (yAssets * inputAmount * dexFee) /
	((xAssets + (xAssets * Slippage / SlippageDenom)) * DexFeeDenom +
	(inputAmount * dexFee)) 
	
	val validR5 = if (outLogic.R9[Long].isDefined) {{
		val inputAmountSecondary = outLogic.R9[Long].get.toBigInt
		val quotePriceSecondary = (yAssets * inputAmountSecondary * dexFee) /
		((xAssets + (xAssets * Slippage / SlippageDenom)) * DexFeeDenom +
		(inputAmount * dexFee)) 
		outLogic.R5[Long].get == quotePriceSecondary
	}} else {{
		outLogic.R5[Long].get == -1
	}}
	
	sigmaProp(
		outLogic.propositionBytes == SELF.propositionBytes &&
		outLogic.value >= SELF.value &&
		outLogic.R4[Long].get == quotePrice &&
		validR5 &&
		outLogic.R6[Coll[Long]].get == SELF.R6[Coll[Long]].get 
	)
}}''')



def generate_proxy_borrow_script(collateralScript, poolNFT, borrowTokenId, currencyId):
	return compile_script(f'''{{
	val collateralBoxScript  = fromBase58("{collateralScript}")
	val minTxFee      = 1000000L
	val minBoxValue   = 1000000L
	val poolNFT       = fromBase58("{poolNFT}")
 	val BorrowTokenId = fromBase58("{borrowTokenId}")
	val PoolNativeCurrency = fromBase58("{currencyId}")
	
	val user          = SELF.R4[Coll[Byte]].get
	val requestedAmounts = SELF.R5[Coll[Long]].get
	val requestAmount = requestedAmounts(0)
	val borrowTokensRequest = requestedAmounts(1)
	val publicRefund  = SELF.R6[Int].get
	val userThresholdPenalty = SELF.R7[(Long, Long)].get
	val userDexNft = SELF.R8[Coll[Byte]].get
	val userPk = SELF.R9[GroupElement].get
	
	val operation = if (OUTPUTS.size < 3) {{
		val refundBox = OUTPUTS(0)
		val deltaErg = SELF.value - refundBox.value

		val validRefundRecipient = refundBox.propositionBytes == user
		val multiBoxSpendRefund = refundBox.R4[Coll[Byte]].get == SELF.id
		val validDeltaErg = deltaErg <= minTxFee
		val validHeight   = HEIGHT >= publicRefund

		val refund = (
			validRefundRecipient  &&
			validDeltaErg &&
			multiBoxSpendRefund &&
			validHeight
		)
		refund
	}} else {{
		val poolBox       = OUTPUTS(0)
		val collateralBox = OUTPUTS(1)
		val userBox       = OUTPUTS(2)

		val collateralTokens = collateralBox.tokens
		val collateral = collateralBox.value
		val collateralBorrowTokens = collateralBox.tokens(0)
		val recordedBorrower = collateralBox.R4[Coll[Byte]].get
		val collateralUserPk = collateralBox.R5[GroupElement].get
		val currentSettings = collateralBox.R6[Coll[Long]].get // (Forced Liquidation, Buffer, iThreshold, Penalty, Automated Actions, More....)
		val forcedLiquidation = currentSettings(0)
		val bufferLiquidation = currentSettings(1)
		val threshold = currentSettings(2)
		val penalty = currentSettings(3)
		val currentQuoteNFT = collateralBox.R7[Coll[Byte]].get

		val loanAmount = collateralBorrowTokens._2

		val validCollateralBoxScript = blake2b256(collateralBox.propositionBytes) == collateralBoxScript
		val validCollateralTokens = collateral == SELF.value - minBoxValue - minTxFee
		val validLoanAmount = (
			borrowTokensRequest == collateralBox.tokens(0)._2 &&
			collateralBorrowTokens._1 == BorrowTokenId &&
			userBox.tokens(0)._1 == PoolNativeCurrency
			)

		val validBorrower = collateralBox.R4[Coll[Byte]].get == user
		val validThresholdPenalty = userThresholdPenalty == (threshold, penalty)
		val validDexNFT = userDexNft == currentQuoteNFT
		val validUserPk = userPk == collateralUserPk
		val validForcedLiquidation = forcedLiquidation > HEIGHT + 65020

		val validInterestIndex = INPUTS(0).tokens(0)._1 == poolNFT // enforced by pool contract

		val validUserScript = userBox.propositionBytes == user
		val validUserLoanAmount = userBox.tokens(0)._2 == requestAmount
		val multiBoxSpendSafety = userBox.R4[Coll[Byte]].get == SELF.id

		val exchange = (
			validCollateralBoxScript &&
			validUserScript &&
			validCollateralTokens &&
			validLoanAmount &&
			validBorrower &&
			validThresholdPenalty &&
			validDexNFT &&
			validUserPk &&
			validForcedLiquidation &&
			validInterestIndex &&
			validUserLoanAmount &&
			multiBoxSpendSafety
		)
		exchange
	}}
	operation || proveDlog(userPk)
}}''')

