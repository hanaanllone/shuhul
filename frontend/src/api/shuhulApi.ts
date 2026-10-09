// const API_BASE =
//   import.meta.env.VITE_API_URL ||
//   "http://localhost:5000";

// export async function analyzeProject(projectData: unknown) {
//   const response = await fetch(
//     `${API_BASE}/api/projects/analyze`,
//     {
//       method: "POST",
//       headers: {
//         "Content-Type": "application/json",
//       },
//       body: JSON.stringify(projectData),
//     }
//   );

//   if (!response.ok) {
//     const error = await response.json().catch(
//       () => ({})
//     );

//     throw new Error(
//       error.message ||
//         "Failed to analyze project."
//     );
//   }

//   return response.json();
// }