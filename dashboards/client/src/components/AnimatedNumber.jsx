import useAnimatedNumber from "../hooks/useAnimatedNumber";

export default function AnimatedNumber({ value, decimals = 0, className = "" }) {
  const animated = useAnimatedNumber(value);
  const factor = Math.pow(10, decimals);
  const rounded = Math.round(animated * factor) / factor;
  return (
    <span className={className}>
      {decimals > 0 ? rounded.toFixed(decimals) : Math.round(rounded)}
    </span>
  );
}
