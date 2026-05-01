import { RouterProvider } from "react-router";
import { router } from "./routes";
import { Toaster } from "sonner";
import { ThemeProvider } from "./contexts/ThemeContext";

export default function App() {
    return (
        <ThemeProvider>
            <RouterProvider router={router} />
            <Toaster richColors position="top-right" />
        </ThemeProvider>
    );
}
