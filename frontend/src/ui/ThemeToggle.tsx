import { IconButton } from "./IconButton";
import { useTheme } from "../theme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <IconButton
      label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      onClick={toggle}
    >
      {theme === "dark" ? "🌙" : "🌞"}
    </IconButton>
  );
}
