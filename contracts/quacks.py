from helpers.node_calls import compile_script


def generate_pool_script(collateralContractScript, childBoxNft, parameterBoxNft):
    return compile_script(f'''{{
	// Constants
	val InterestNFT = fromBase58("{childBoxNft}")
	val ParamaterBoxNft = fromBase58("{parameterBoxNft}")
	val CollateralContractScript = fromBase58("{collateralContractScript}")

	val MaxLendTokens = 9000000000000010L // Set 1,000,000 higher than true maximum so that genesis lend token value is 1.
	val MaxBorrowTokens = 9000000000000000L
	val BorrowTokenDenomination = 10000000000000000L.toBigInt
	val MinimumBoxValue = 1000000L
	val LendTokenMultipler = 1000000000000000L.toBigInt
	val LiquidationThresholdDenomination = 1000
	val defaultBufferHeight = 100000000L

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
		successorPooledTokens._1 == currentPooledTokens._1 &&
		successor.tokens.size == SELF.tokens.size &&
		successor.R4[Boolean].get &&
		successor.R5[Boolean].get &&
		successor.R6[Boolean].get &&
		successor.R7[Boolean].get &&
		successor.R8[Boolean].get &&
		successor.R9[Boolean].get
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
		val minFee = feeSettings(5)
		
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
		val validServiceTokens = serviceFeeAssets >= max(totalServiceFee, minFee) && serviceFeeTokens._1 == currentPooledTokens._1
	
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
		val collateralIndex = OUTPUTS.map{{
			(b: Box) => b.id
		}}.indexOf(collateralBox.id, 0)
		val collateralValue = collateralBox.value
		val collateralBorrowTokens = collateralBox.tokens(0)
		val collateralBorrower = collateralBox.R4[Coll[Byte]].get
		val collateralUserPk = collateralBox.R5[GroupElement].get
		val bufferLiquidationHeight = collateralBox.R6[Long].get
		val collateralQuoteNFT = collateralBox.R7[Coll[Byte]].get
		val verifiedSpendingNFT = collateralBox.R8[Coll[Byte]].get
		val loanAmount = collateralBorrowTokens._2.toBigInt * borrowTokenValue / BorrowTokenDenomination
	
		val fQuote = OUTPUTS.filter{{
		(b: Box) => b.tokens.size > 0 && customLogicNFTs.exists{{
			(NFT: Coll[Byte]) => b.tokens(0)._1 == NFT && NFT == collateralQuoteNFT
			}}
		}}(0)
		val quoteReport = fQuote.R4[Coll[Long]].get 
		val borrowLimit = quoteReport(0)
		val quotePrice = quoteReport(1)
		val threshold = quoteReport(2)
		val finalBorrowedFromPool = successorBorrowTokensCirculating * borrowTokenValue / BorrowTokenDenomination
		val isUnderBorrowLimit = finalBorrowedFromPool < borrowLimit
		val isQuotedBoxValid = collateralIndex == fQuote.R9[Coll[Int]].get(0) - 1
		
		val isCorrectCollateralAmount = quotePrice >= loanAmount.toBigInt * threshold.toBigInt / LiquidationThresholdDenomination.toBigInt
		val isCorrectBufferHeight = bufferLiquidationHeight == defaultBufferHeight
		
		val isCollateralTokensPreserved = collateralBorrowTokens._2 + successorBorrowTokens._2 == currentBorrowTokens._2
		
		val isAssetsInPoolDecreasing = deltaAssetsInPool < 0
		val isAssetAmountValid = deltaAssetsInPool * -1 == loanAmount
		val isTotalBorrowedValid = deltaTotalBorrowed == collateralBorrowTokens._2
		(
			commonConditions &&
			successorLendTokens == currentLendTokens &&
			isCollateralTokensPreserved &&
			isAssetsInPoolDecreasing &&
			isAssetAmountValid &&
			isTotalBorrowedValid &&
			isCorrectBufferHeight &&
			isCorrectCollateralAmount &&
			isUnderBorrowLimit &&
			isQuotedBoxValid
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
	val storageRentLength = 980000L // Slightly less than full storage rent length for sanity

	// Current Collateral Box
	val currentScript = SELF.propositionBytes
	val currentValue = SELF.value
	val currentBorrowTokens = SELF.tokens(0)
	val iCollateralTokens = SELF.tokens.slice(1, SELF.tokens.size)
	val currentBorrower = SELF.R4[Coll[Byte]].get
	val currentUserPk = SELF.R5[GroupElement].get
	val iBufferLiquidation = SELF.R6[Long].get
	val currentQuoteNFT = SELF.R7[Coll[Byte]].get
	val iSpendingNFT = SELF.R8[Coll[Byte]].get
	val loanAmount = currentBorrowTokens._2
	
	// Extract values from interest box
	val interestBox = CONTEXT.dataInputs.filter{{
		(b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == InterestNFT
	}}(0)
	val borrowTokenValue = interestBox.R5[BigInt].get

	val totalOwed = loanAmount.toBigInt * borrowTokenValue / BorrowTokenDenomination
	
	// Fetch Collateral Quote Box
	val fQuotes = OUTPUTS.filter{{
		(b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == currentQuoteNFT
	}}
	
	if (fQuotes.size > 0) {{
		val fQuote = fQuotes.getOrElse(0, SELF)
		val quoteReport = fQuote.R4[Coll[Long]].get
		val quotePrice = quoteReport(1)
		val iThreshold = quoteReport(2)
		val iPenalty = quoteReport(3)
		
		val fCollaterals = OUTPUTS.filter{{
			(b: Box) => b.propositionBytes == SELF.propositionBytes
		}}
		
		val isOnlyOneCollateralInput = INPUTS.filter{{
			(b: Box) => b.propositionBytes == SELF.propositionBytes
		}}.size == 1 // Possibly can replace with context var
		
		val fRepayments = OUTPUTS.filter{{
			(b: Box) => blake2b256(b.propositionBytes) == RepaymentContractScript
		}} 
		
		if (fCollaterals.size > 0) {{
			val fCollateral = fCollaterals.getOrElse(0, SELF) // TODO: Check if necessary
			val collateralIndex = OUTPUTS.map{{
				(b: Box) => b.id
			}}.indexOf(fCollateral.id, 0)
			val isQuotedBoxValid = collateralIndex == fQuote.R9[Coll[Int]].get(0) - 1
		
			val fCollateralValue = fCollateral.value
			val fCollateralBorrowTokens = fCollateral.tokens(0)
			val fCollateralTokens = fCollateral.tokens.slice(1, fCollateral.tokens.size)
			val fCollateralBorrower = fCollateral.R4[Coll[Byte]].get
			val fCollateralUserPk = fCollateral.R5[GroupElement].get
			val fBufferLiquidation = fCollateral.R6[Long].get
			val fCollateralQuoteNFT = fCollateral.R7[Coll[Byte]].get
			val fSpendingNFT = fCollateral.R8[Coll[Byte]].get
			
			val bufferLiquidationSame = fBufferLiquidation == iBufferLiquidation
			
			val fCollateralCommon = (
				fCollateralBorrowTokens._1 == currentBorrowTokens._1 &&
				fCollateralBorrower == currentBorrower &&
				fCollateralUserPk == currentUserPk &&
				fCollateralQuoteNFT == currentQuoteNFT &&
				iSpendingNFT == fSpendingNFT &&
				isOnlyOneCollateralInput &&
				isQuotedBoxValid
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
				val isTokensUntouched = fCollateralTokens == iCollateralTokens
				
				val partialRepayment = sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Tokens, Buffer)
					fCollateralCommon &&
					fCollateralValue >= currentValue &&
					validBorrowTokens &&
					isTokensUntouched &&
					bufferLiquidationSame &&
					// Complete Repayment Checks (Borrow Token Amount, Loan Token Amount*)
					fRepaymentCommon &&
					fRepaymentBorrowTokens._2 == currentBorrowTokens._2 - fCollateralBorrowTokens._2 &&
					isSufficientCollateral
				)
				partialRepayment
			}} else {{
				// Prep Liquidation and Adjust Collateteral
				// Specific Ready to liquidate conditions
				val finalTotalOwed = fCollateralBorrowTokens._2 * borrowTokenValue / BorrowTokenDenomination
				val isSufficientCollateral = quotePrice >= finalTotalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt
				
				val readyToLiquidate = sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					fCollateralValue >= currentValue - MinimumTransactionFee &&
					fCollateral.tokens == SELF.tokens &&
					fBufferLiquidation > HEIGHT && fBufferLiquidation < HEIGHT + 5 &&
					!isSufficientCollateral				
				)
							
				val isValidCollateral = quotePrice >= totalOwed.toBigInt * iThreshold.toBigInt / LiquidationThresholdDenom.toBigInt
				val nftProofGiven = INPUTS.filter{{
					(b: Box) => b.tokens.size > 0 && b.tokens(0)._1 == fSpendingNFT
				}}.size > 0
				val adjustCollateral = (sigmaProp(nftProofGiven) || proveDlog(currentUserPk)) && 
				sigmaProp(
					// Complete Collateral Checks (Value, Borrow Token Amount, Settings)
					fCollateralCommon &&
					fCollateralValue >= 3 * MinimumBoxValue + MinimumTransactionFee &&
					isValidCollateral &&
					fCollateralBorrowTokens == currentBorrowTokens
				)
				readyToLiquidate || adjustCollateral
			}}
			
		}} else {{
			val collateralIndex = INPUTS.map{{
				(b: Box) => b.id
			}}.indexOf(SELF.id, 0)
			val isQuotedBoxValid = collateralIndex == fQuote.R9[Coll[Int]].get(0) * -1 - 1
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
				HEIGHT > SELF.creationInfo._1 + storageRentLength
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
				isQuotedBoxValid
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
			validBorrowerCollateral
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


def generate_logic_script():
	return compile_script(f'''{{	
	val Slippage = 2.toBigInt
	val SlippageDenom = 100.toBigInt
	val DexFeeDenom = 1000.toBigInt
	val MaximumNetworkFee = 5000000
	val LargeMultiplier = 1000000000000L

	val outLogic = OUTPUTS.filter {{
		(b : Box) => b.tokens.size > 0 && b.tokens(0) == SELF.tokens(0)
	}}(0)

	val iReport = outLogic.R4[Coll[Long]].get
	val iBorrowLimit = iReport(0)
	val iDexNfts = SELF.R5[Coll[Coll[Byte]]].get
	val iAssetThresholds = SELF.R6[Coll[Long]].get
	
	val fReport = outLogic.R4[Coll[Long]].get
	val fBorrowLimit = fReport(0)
	val fQuotePrice = fReport(1)
	val fAggregateThreshold = fReport(2)
	val fAggregatePenalty = fReport(3) 
	val fDexNfts = outLogic.R5[Coll[Coll[Byte]]].get
	val primaryDexNft = fDexNfts(0)
	val secondaryDexNfts = fDexNfts.slice(1, fDexNfts.size)
	val fAssetThresholds = outLogic.R6[Coll[Long]].get
	val primaryThreshold = fAssetThresholds(0)
	val secondaryThresholds = fAssetThresholds.slice(1, fAssetThresholds.size)
	val fOrderedAssetAmounts = outLogic.R7[Coll[Long]].get
	val fOrderedQuotedAssetIds = outLogic.R8[Coll[Coll[Byte]]].get
	val fHelperIndices = outLogic.R9[Coll[Int]].get
	val fBoxIndex = fHelperIndices(0)
	val fDexStartIndex = fHelperIndices(1)

	val scriptRetained = outLogic.propositionBytes == SELF.propositionBytes
	val quoteSettingsRetained = fDexNfts == iDexNfts && fAssetThresholds == iAssetThresholds

	// 1 -> 0, 2 -> 1, 3 -> 2, 4 -> 3 For OUTPUTS
	// -1 -> 0, -2 -> 1, -3 -> 2, -4 -> 3 For INPUTS
	val boxToQuote = if (fBoxIndex > 0) {{
		OUTPUTS(fBoxIndex - 1)
	}} else {{
		INPUTS(fBoxIndex * -1 - 1)
	}}	

	val primaryDexBox = CONTEXT.dataInputs(fDexStartIndex)
	val dexDIns = CONTEXT.dataInputs.slice(fDexStartIndex + 1, CONTEXT.dataInputs.size) // Primary DEX Box at fDexStartIndex
	val dInsMatchesAssetsSize = dexDIns.size == fOrderedAssetAmounts.size && dexDIns.size == secondaryDexNfts.size
	val collateralValueInErgs = dexDIns.zip(fOrderedAssetAmounts).fold(0L.toBigInt, {{(z:BigInt, p: (Box, Long)) => (
	{{
		if (p._2 > 0) {{
			val dexBox = p._1
			val dexReservesErg = dexBox.value
			val dexReservesToken = dexBox.tokens(2)
			val dexFee = dexBox.R4[Int].get
			val inputAmount = p._2
			val collateralMarketValue = (dexReservesErg.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
			  ((dexReservesToken._2.toBigInt + (dexReservesToken._2.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexFeeDenom.toBigInt +
			  (inputAmount.toBigInt * dexFee.toBigInt))
	
			z + collateralMarketValue
		}} else {{
			z
		}}
	}}
	)}})

	val totalBoxValue = boxToQuote.value.toBigInt + collateralValueInErgs.toBigInt - MaximumNetworkFee.toBigInt 

	val aggregateThresholdPrimarySum = (boxToQuote.value.toBigInt * LargeMultiplier * primaryThreshold) / totalBoxValue
	val aggregateThresholdSecondarySum = fOrderedAssetAmounts.indices.fold(0L.toBigInt, {{(z:BigInt, index: Int) => (
	{{
		val inputAmount = fOrderedAssetAmounts(index)
		if (inputAmount > 0) {{
			val dexBox = dexDIns(index)
			val dexReservesErg = dexBox.value
			val dexReservesToken = dexBox.tokens(2)
			val dexFee = dexBox.R4[Int].get
			
			val collateralMarketValue = (dexReservesErg.toBigInt * inputAmount.toBigInt * dexFee.toBigInt) /
				((dexReservesToken._2.toBigInt + (dexReservesToken._2.toBigInt * Slippage.toBigInt / 100.toBigInt)) * DexFeeDenom.toBigInt +
				(inputAmount.toBigInt * dexFee.toBigInt))
			val threshold = secondaryThresholds(index)
	
			z + (collateralMarketValue * LargeMultiplier * threshold) / totalBoxValue
		}} else {{
			z
		}}
	}}
	)}})
	val aggregateThreshold = aggregateThresholdPrimarySum + aggregateThresholdSecondarySum
	val zippedOrderedAssetsList = fOrderedQuotedAssetIds.zip(fOrderedAssetAmounts)
	val matchingOrderedListSize = fOrderedAssetAmounts.size == fOrderedQuotedAssetIds.size
	val allAssetsCounted = boxToQuote.tokens.slice(1,boxToQuote.tokens.size).forall{{
		(token: (Coll[Byte], Long)) => zippedOrderedAssetsList.exists {{
			(reportedToken: (Coll[Byte], Long)) => reportedToken == token
		}}
	}}

	val missingAssetsSize = fOrderedAssetAmounts.size - (boxToQuote.tokens.size - 1) // Ignores the borrow tokens
	val correctNumberOfZeroes = fOrderedAssetAmounts.filter{{
		(Amount: Long) => {{
		Amount == 0L
		}}
	}}.size == missingAssetsSize

	// Also validates the dexNFTs match the settings
	val assetsOrderedCorrectly = secondaryDexNfts.indices.forall{{
		(index: Int) =>
		val dexBox = dexDIns(index)
		val dexNFT = secondaryDexNfts(index)
		val dexTokenId = dexBox.tokens(2)._1
		val reportedAssetId = fOrderedQuotedAssetIds(index)
		(
			dexNFT == dexBox.tokens(0)._1 &&
			reportedAssetId == dexTokenId
		)
	}}

	val validAggregateThreshold = aggregateThreshold == fAggregateThreshold * LargeMultiplier
	val validPenalty = fAggregatePenalty == 30L // Static Penalty as an example

	val xAssets = primaryDexBox.value.toBigInt
	val yAssets = primaryDexBox.tokens(2)._2.toBigInt

	val dexFee = primaryDexBox.R4[Int].get.toBigInt
	val quotePrice = (yAssets * totalBoxValue * dexFee) /
	((xAssets + (xAssets * Slippage / SlippageDenom)) * DexFeeDenom +
	(totalBoxValue * dexFee))

	val isValidPrimaryDexBox = primaryDexBox.tokens(0)._1 == primaryDexNft

	val validQuote = quotePrice == fQuotePrice

	sigmaProp(
		scriptRetained &&
		quoteSettingsRetained &&
		validQuote &&
		validPenalty &&
		allAssetsCounted &&
		assetsOrderedCorrectly &&
		dInsMatchesAssetsSize &&
		matchingOrderedListSize &&
		correctNumberOfZeroes &&
		iBorrowLimit == fBorrowLimit &&
		isValidPrimaryDexBox
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

