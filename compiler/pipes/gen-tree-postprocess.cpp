#include "compiler/pipes/gen-tree-postprocess.h"

GenTreePostprocessPass::builtin_fun GenTreePostprocessPass::get_builtin_function(const std::string &name) {
  static map<std::string, builtin_fun> functions = {
    {"strval", {op_conv_string, 1}},
    {"intval", {op_conv_int, 1}},
    {"boolval", {op_conv_bool, 1}},
    {"floatval", {op_conv_float, 1}},
    {"arrayval", {op_conv_array, 1}},
    {"uintval", {op_conv_uint, 1}},
    {"longval", {op_conv_long, 1}},
    {"ulongval", {op_conv_ulong, 1}},
    {"fork", {op_fork, 1}},
    {"pow", {op_pow, 2}}
  };
  auto it = functions.find(name);
  if (it == functions.end()) {
    return {op_err, -1};
  }
  return it->second;
}


VertexPtr GenTreePostprocessPass::on_enter_vertex(VertexPtr root, LocalT *) {
  if (root->type() == op_func_call) {
    VertexAdaptor<op_func_call> call = root;

    auto builtin = get_builtin_function(call->get_string());
    if (builtin.op != op_err && call->size() == builtin.args) {
      VertexRange args = call->args();
      if (builtin.op == op_fork) {
        args[0]->fork_flag = true;
      }
      VertexPtr new_root = create_vertex(builtin.op, vector<VertexPtr>(args.begin(), args.end()));
      ::set_location(new_root, root->get_location());
      return new_root;
    }
  }

  if (root->type() == op_minus || root->type() == op_plus) {
    VertexAdaptor<meta_op_unary> minus = root;
    VertexPtr maybe_num = minus->expr();
    if (maybe_num->type() == op_int_const || maybe_num->type() == op_float_const) {
      VertexAdaptor<meta_op_num> num = maybe_num;
      string prefix = root->type() == op_minus ? "-" : "";
      num->str_val = prefix + num->str_val;
      minus->expr() = VertexPtr();
      return num;
    }
  }

  if (root->type() == op_set) {
    VertexAdaptor<op_set> set_op = root;
    if (set_op->lhs()->type() == op_list_ce) {
      vector<VertexPtr> next;
      next = set_op->lhs()->get_next();
      next.push_back(set_op->rhs());
      auto list = VertexAdaptor<op_list>::create(next);
      ::set_location(list, root->get_location());
      list->phpdoc_token = root.as<op_set>()->phpdoc_token;
      return list;
    }
  }

  if (root->type() == op_func_call && root->get_string() == "call_user_func_array") {
    VertexRange args = root.as<op_func_call>()->args();
    kphp_error ((int)args.size() == 2, dl_pstr("Call_user_func_array expected 2 arguments, got %d", (int)root->size()));
    kphp_error_act (args[0]->type() == op_string, "First argument of call_user_func_array must be a const string", return root);
    auto arg = VertexAdaptor<op_varg>::create(args[1]);
    ::set_location(arg, args[1]->get_location());
    auto new_root = VertexAdaptor<op_func_call>::create(arg);
    ::set_location(new_root, arg->get_location());
    new_root->str_val = args[0].as<op_string>()->str_val;
    return new_root;
  }

  return root;
}

VertexPtr GenTreePostprocessPass::on_exit_vertex(VertexPtr root, LocalT *) {
  if (root->type() == op_var) {
    if (is_superglobal(root->get_string())) {
      root->extra_type = op_ex_var_superglobal;
    }
  }

  if (root->type() == op_arrow) {
    VertexAdaptor<op_arrow> arrow = root;
    VertexPtr rhs = arrow->rhs();

    if (rhs->type() == op_func_name) {
      auto inst_prop = VertexAdaptor<op_instance_prop>::create(arrow->lhs());
      ::set_location(inst_prop, root->get_location());
      inst_prop->set_string(rhs->get_string());

      return inst_prop;
    } else if (rhs->type() == op_func_call) {
      vector<VertexPtr> new_next;
      const vector<VertexPtr> &old_next = rhs.as<op_func_call>()->get_next();

      new_next.push_back(arrow->lhs());
      new_next.insert(new_next.end(), old_next.begin(), old_next.end());

      auto new_root = VertexAdaptor<op_func_call>::create(new_next);
      ::set_location(new_root, root->get_location());
      new_root->extra_type = op_ex_func_member;
      new_root->str_val = rhs->get_string();

      return new_root;
    } else {
      kphp_error (false, "Operator '->' expects property or function call as its right operand");
    }
  }

  return root;
}

bool GenTreePostprocessPass::is_superglobal(const string &s) {
  static set<string> names = {
    "_SERVER",
    "_GET",
    "_POST",
    "_FILES",
    "_COOKIE",
    "_REQUEST",
    "_ENV"
  };
  return names.find(s) != names.end();
}
