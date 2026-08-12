import { ToastProvider } from "./context/ToastContext";
import HRDashboard from "./pages/HRDashboard";

function App() {
  return (
    <ToastProvider>
      <HRDashboard />
    </ToastProvider>
  );
}

export default App;
