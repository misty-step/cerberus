defmodule Cerberus.Verdict.CostTest do
  use ExUnit.Case, async: true

  alias Cerberus.Verdict.Cost

  describe "calculate/3" do
    test "computes cost for known model" do
      # kimi-k2.5: input=0.45/M, output=2.20/M
      cost = Cost.calculate(1_000_000, 1_000_000, "moonshotai/kimi-k2.5")
      assert_in_delta cost, 2.65, 0.001
    end

    test "strips openrouter/ prefix for lookup" do
      bare = Cost.calculate(1_000_000, 1_000_000, "moonshotai/kimi-k2.5")
      prefixed = Cost.calculate(1_000_000, 1_000_000, "openrouter/moonshotai/kimi-k2.5")
      assert_in_delta bare, prefixed, 0.001
    end

    test "falls back to default pricing for unknown model" do
      # default: input=0.50/M, output=1.50/M
      cost = Cost.calculate(1_000_000, 1_000_000, "unknown/model")
      assert_in_delta cost, 2.00, 0.001
    end

    test "zero tokens yields zero cost" do
      assert Cost.calculate(0, 0, "moonshotai/kimi-k2.5") == 0.0
    end

    test "scales linearly with token count" do
      half = Cost.calculate(500_000, 500_000, "moonshotai/kimi-k2.5")
      full = Cost.calculate(1_000_000, 1_000_000, "moonshotai/kimi-k2.5")
      assert_in_delta half * 2, full, 0.001
    end
  end
end
