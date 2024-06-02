```scala
{	
    val p = 1000000L.toBigInt // p is our precision
	def lnX(x: BigInt): BigInt = {
		(
			x -
			(x * x) / (2 * p) +
			(x * x * x) / (3 * p * p) - 
			(x * x * x * x) / (4 * p * p * p) + 
			(x * x * x * x * x) / (5 * p * p * p * p) - 
			(x * x * x * x * x * x) / (6 * p * p * p * p * p)
		)
	}
	
	
	def isValidSquareRoot(values: (BigInt, BigInt)): Boolean = {
		val originalValue = values._1
		val supposedSquareRoot = values._2
		val calculatedValue = (supposedSquareRoot * supposedSquareRoot)
        val error = (originalValue - calculatedValue)
        val errorMargin = max(error, -1 * error)
        
        // Adaptive error margin based on the supposed square root
        val adaptiveMargin = 2 * supposedSquareRoot + 1
        errorMargin < adaptiveMargin
	}

	val dexNFT = fromBase58("BJbaZAXMoFm9gi2MBXA9eyPi38ugjKZ66SQrnwQmoDNj")
	val reportedValue = (100000000000000L.toBigInt * CONTEXT.dataInputs(0).tokens(2)._2.toBigInt) / CONTEXT.dataInputs(0).value.toBigInt
	val isValidReport = CONTEXT.dataInputs(0).tokens(0)._1 == dexNFT

	val n = 100 // Size of rolling window to maintain
	val upatesInAYear = 900
	val sqrtUpdatesInAYear = 30
	val updateFrequency = 292
	val iLogReturns = SELF.R4[Coll[Long]].get
	val iStart = SELF.R5[Int].get
	val iVolatility = SELF.R6[Long].get
	val iHeight = SELF.R7[Long].get
	val previousPrice = SELF.R8[Long].get
	
	val successor = OUTPUTS(0)
	val fLogReturns = successor.R4[Coll[Long]].get
	val fStart = successor.R5[Int].get
	val fVolatility = successor.R6[Long].get.toBigInt
	val fHeight = successor.R7[Long].get
	val currentPrice = successor.R8[Long].get
	val annualizedVolatility = successor.R9[Long].get

	val sumOfLogReturns = fLogReturns.fold(0L.toBigInt, {(z: BigInt, price: Long) => z + price.toBigInt})
	
	val mean = sumOfLogReturns / n
	val squaredDiffSum = fLogReturns.fold(0L.toBigInt, {(z: BigInt, price: Long) => z + (price.toBigInt - mean) * (price.toBigInt - mean)})  // Sum of squared differences from the mean	
	val newEntry = lnX((currentPrice.toBigInt * p / previousPrice.toBigInt)-p)
	val sampleVariance = squaredDiffSum / (n - 1)
	
	sigmaProp(
		iHeight < HEIGHT &&
		fHeight == iHeight + updateFrequency &&
		iLogReturns.slice(0, iStart) == fLogReturns.slice(0, iStart) &&
		iLogReturns.slice(iStart + 1, n) == fLogReturns.slice(iStart + 1, n) &&
		fLogReturns(iStart) == newEntry &&
		fStart == (iStart + 1) % n &&
		isValidSquareRoot((sampleVariance, fVolatility)) &&
		annualizedVolatility == fVolatility * sqrtUpdatesInAYear &&
		reportedValue == currentPrice &&
		isValidReport 
	)
}
```
