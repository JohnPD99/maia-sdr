//
// Copyright (C) 2023 Daniel Estevez <daniel@destevez.net>
//
// This file is part of maia-sdr
//
// SPDX-License-Identifier: MIT
//

`timescale 1ps/1ps

module tb
  (
   input wire         clk,
   input wire         rst,
   input wire         clk3x_clk,
   input wire         clk3x_rst,
   input wire         clken,
   input wire [46:0]  a,
   //input wire         peak_detect
   output wire [94:0] out
   //output wire        is_greater
   );

   glbl glbl ();

   dut dut
     (.clk(clk), .rst(rst), .clk3x_clk(clk3x_clk), .clk3x_rst(clk3x_rst),
      .clken(clken), .a(a), .out(out));

`ifdef COCOTB_SIM
   initial begin
      $dumpfile("dump.vcd");
      $dumpvars(0, dut);
   end
`endif
endmodule // tb
