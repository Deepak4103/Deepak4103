import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import GraphingCalculator from "@/pages/GraphingCalculator";
import { Toaster } from "@/components/ui/sonner";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<GraphingCalculator />} />
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="top-center" />
    </div>
  );
}

export default App;
