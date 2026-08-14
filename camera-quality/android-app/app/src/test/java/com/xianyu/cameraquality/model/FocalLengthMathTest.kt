package com.xianyu.cameraquality.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FocalLengthMathTest {
    @Test
    fun fullFrameSensorReturnsPhysicalFocalLength() {
        val equivalent = FocalLengthMath.equivalent35mm(
            focalLengthMm = 85.0,
            sensorWidthMm = 36.0,
            sensorHeightMm = 24.0,
        )

        assertEquals(85.0, equivalent!!, 0.0001)
    }

    @Test
    fun smallerSensorAppliesCropFactor() {
        val equivalent = FocalLengthMath.equivalent35mm(
            focalLengthMm = 15.0,
            sensorWidthMm = 7.2,
            sensorHeightMm = 5.4,
        )

        assertEquals(72.11, equivalent!!, 0.02)
    }

    @Test
    fun invalidSensorSizeReturnsNull() {
        assertNull(FocalLengthMath.equivalent35mm(15.0, 0.0, 5.4))
    }

    @Test
    fun choosesDistanceFromClosestReportedFocalLength() {
        assertEquals(3.0, FocalLengthMath.distanceFromTarget(listOf(24.0, 82.0), 85.0), 0.0)
    }
}
