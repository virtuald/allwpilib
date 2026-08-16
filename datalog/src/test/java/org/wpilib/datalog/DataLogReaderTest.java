// Copyright (c) FIRST and other WPILib contributors.
// Open Source Software; you can modify and/or share it under the terms of
// the WPILib BSD license file in the root directory of this project.

package org.wpilib.datalog;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class DataLogReaderTest {
  @Test
  void rejectsExtraHeaderLargerThanInput() {
    byte[] input = {
      'W', 'P', 'I', 'L', 'O', 'G', 0x00, 0x01,
      (byte) 0xff, (byte) 0xff, (byte) 0xff, (byte) 0xff
    };
    DataLogReader reader = new DataLogReader(ByteBuffer.wrap(input));

    assertFalse(reader.isValid());
    assertEquals(0, reader.getVersion());
    assertEquals("", reader.getExtraHeader());
    assertFalse(reader.iterator().hasNext());
    AtomicInteger records = new AtomicInteger();
    reader.forEach(record -> records.incrementAndGet());
    assertEquals(0, records.get());
  }
}
