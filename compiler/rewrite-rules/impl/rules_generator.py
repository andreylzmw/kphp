from pathlib import Path
from string import Template
from typing import Optional, Tuple, List, Set

from .vertex_schema import VertexSchema
from .rules_parser import RulesParser, Rule
from .rules_parser import Expr
from .code_printer import CodePrinter

# TODO:
# - measure compile-time effect of rewrite rules (early_opt pass)

OUTPUT_H_TEMPLATE = """// Compiler for PHP (aka KPHP)
// Copyright (c) 2022 LLC «V Kontakte»
// Distributed under the GPL v3 License, see LICENSE.notice.txt

// Code generated by rules-gen.py; DO NOT EDIT!
// Source file: compiler/rewrite-rules/${name}.rules

#pragma once

#include "compiler/data/data_ptr.h"

void run_${name}_rules_pass(FunctionPtr f);
"""


OUTPUT_CPP_TEMPLATE = """// Compiler for PHP (aka KPHP)
// Copyright (c) 2022 LLC «V Kontakte»
// Distributed under the GPL v3 License, see LICENSE.notice.txt

// Code generated by rules-gen.py; DO NOT EDIT!
// Source file: compiler/rewrite-rules/${name}.rules

#include "compiler/rewrite-rules/rules_runtime.h"
#include "./${name}.h"
#include "compiler/function-pass.h"
#include "compiler/vertex-util.h"
#include <string_view>

class GeneratedPass final : public FunctionPassBase {
private:
  rewrite_rules::Context &ctx_;
  bool vertex_updated_;

public:
  explicit GeneratedPass(rewrite_rules::Context &ctx) : ctx_{ctx}, vertex_updated_{false} {}

  std::string get_description() override {
    return "Apply ${name} rewrite rules";
  }
  
  VertexPtr on_exit_vertex(VertexPtr v) override {
    // apply the rewrites until the vertex stops changing
    int num_runs = 0;
    while (true) {
      vertex_updated_ = false;
      VertexPtr v2 = rewrite_vertex(v);
      if (!vertex_updated_) {
        return v;
      }
      v = v2;
      num_runs++;
      // this should never happen, but it could if there are rules like this: A -> B, B -> A
      kphp_assert(num_runs < 10);
    }
  }

  VertexPtr rewrite_vertex(VertexPtr v) {
    using namespace rewrite_rules;
${on_exit_vertex_body}
  }

${vertex_methods}
};

void run_${name}_rules_pass(FunctionPtr f) {
  GeneratedPass pass{rewrite_rules::get_context()};
  run_function_pass(f, &pass);
}
"""


class RulesGeneratorResult:
    def __init__(self, h_src: str, cpp_src: str):
        self.h_src: str = h_src
        self.cpp_src: str = cpp_src


class RulesGenerator:
    def __init__(self, rules_filename: str, vertex_schema_filename: str):
        rules_path = Path(rules_filename)
        self.parser = RulesParser(rules_filename, rules_path.read_text())
        self.name = rules_path.stem
        self.short_rules_filename = rules_path.name
        self.rules_filename = rules_filename
        self.rules_by_prefix = {}
        self.vertex_schema = VertexSchema(vertex_schema_filename)

    def generate_rules(self) -> RulesGeneratorResult:
        rules = self.parser.parse_file()
        for rule in rules:
            prefix = rule.match_expr.op
            if prefix in self.rules_by_prefix:
                self.rules_by_prefix[prefix].append(rule)
            else:
                self.rules_by_prefix[prefix] = [rule]
        printer = CodePrinter(self.short_rules_filename, 4)
        printer.write_and_enter_indent("switch (v->type()) {")
        for op, rules in self.rules_by_prefix.items():
            printer.write_and_enter_indent(f"case {op}:")
            printer.write_line(f"return on_{op}_(v.as<{op}>());")
            printer.leave_indent()
        printer.write_and_enter_indent(f"default:")
        printer.write_line("return v; // no matches")
        printer.leave_indent()
        printer.leave_indent_and_write("}")
        on_exit_vertex_body = printer.get_result()
        vertex_methods = self.__generate_vertex_methods()
        h_src = Template(OUTPUT_H_TEMPLATE).substitute(
            name=self.name,
        )
        cpp_src = Template(OUTPUT_CPP_TEMPLATE).substitute(
            name=self.name,
            on_exit_vertex_body=on_exit_vertex_body,
            vertex_methods=vertex_methods,
        )
        return RulesGeneratorResult(h_src, cpp_src)

    def __generate_vertex_methods(self) -> str:
        printer = CodePrinter(self.short_rules_filename, 2)
        for op, rules in self.rules_by_prefix.items():
            printer.write_and_enter_indent(f"VertexPtr on_{op}_(VertexAdaptor<{op}> v_) {{")
            printer.write_line("using namespace rewrite_rules;")
            printer.break_line()
            for rule in rules:
                self.__print_rule(rule, printer)
            printer.write_line("return v_; // no matches")
            printer.leave_indent_and_write("}")
            printer.break_line()
        return printer.get_result()

    def __print_rule(self, rule: Rule, printer: CodePrinter):
        # write comment
        def write_comment_section(tag: str, comment: str):
            printer.write(f"//   {tag}: ")
            for i, s in enumerate(comment.split("\n")):
                printer.write_line(s if i == 0 else f"//          {s}")
        printer.write_line(f"// {self.short_rules_filename}:{rule.line}")
        write_comment_section("pattern", rule.match_expr.source)
        write_comment_section("rewrite", rule.rewrite_expr.source)
        # write pattern matching body
        printer.write_and_enter_indent("do {")
        vars_declared = set()
        self.print_matcher_cond(rule.match_expr, "v_", printer, vars_declared)
        self.__print_where_cond(rule.cond, printer)
        for v in rule.let_list:
            printer.write_line(f"auto {v.name} = {v.expr};", v.line)
            if v.checked:
                printer.write_line(f"if (!{v.name}) {{ break; }}", v.line)
        can_rewrite_inplace = rule.match_expr.op == rule.rewrite_expr.op and not self.vertex_schema.get(rule.match_expr.op).is_variadic()
        # at this point the match is already successful
        printer.write_line("vertex_updated_ = true;")
        # retire vertices that are not needed (adds them to cache)
        retire_list: List[str] = []
        self.__collect_unnamed(retire_list, "v_", rule.match_expr)
        for expr in retire_list:
            if can_rewrite_inplace and expr == "v_":
                continue  # do not retire v_ if we're about to rewrite it inplace
            printer.write_line(f"retire_vertex(ctx_, {expr});")
        if can_rewrite_inplace:
            args = []
            used_vars = set()
            for member in rule.rewrite_expr.members:
                args.append(self.__generate_replacement_vertex(member, used_vars))
            printer.write_line("v_->set_children(0, " + ', '.join(args) + ");", rule.rewrite_expr.line)
            if rule.rewrite_expr.vertex_string:
                printer.write_line(f"v_->set_string({rule.rewrite_expr.vertex_string});")
            printer.write_line(f"return v_; // modified inplace")
        else:
            # construct a replacement vertex
            used_vars = set()
            replacement = self.__generate_replacement_vertex(rule.rewrite_expr, used_vars)
            printer.write_line(f"auto replacement_ = {replacement};", rule.rewrite_expr.line)
            self.__print_set_location(rule.rewrite_expr, printer)
            printer.write_line(f"return replacement_;")
        printer.leave_indent_and_write("} while (false);")
        printer.break_line()

    def __collect_unnamed(self, dst: List[str], name: str, e: Expr):
        if not e.name and self.__is_cachable_op(e.op):
            dst.append(name)
        if e.op == Expr.OP_ANY:
            if e.name == "_":
                dst.append(name)
            return
        vertex_info = self.vertex_schema.get(e.op)
        for i, subexpr in enumerate(e.members):
            arg_info, range_offset = vertex_info.get_arg(i, len(e.members))
            arg_expr = f"{name}->{arg_info.name}()" if range_offset is None else f"{name}->{arg_info.name}()[{range_offset}]"
            if subexpr.op != Expr.OP_ANY and subexpr.members:
                arg_expr = f"{arg_expr}.as<{subexpr.op}>()"
            self.__collect_unnamed(dst, arg_expr, subexpr)

    def __print_set_location(self, e: Expr, printer: CodePrinter):
        if e.op != Expr.OP_ANY:
            vertex_info = self.vertex_schema.get(e.op)
            if not vertex_info.has_children():
                # no need to set the location recursively
                printer.write_line("replacement_.set_location(v_);")
                return
        printer.write_line("replacement_.set_location_recursively(v_);")

    def __generate_replacement_vertex(self, e: Expr, used_vars: Set[str]) -> str:
        if e.op == Expr.OP_ANY:
            # if some vertex is used in rewrite action more than once, clone it
            if e.name in used_vars:
                return f"{e.name}.clone()"
            used_vars.add(e.name)
            return e.name
        args = []
        if e.vertex_string:
            args.append(e.vertex_string)
        for member in e.members:
            args.append(self.__generate_replacement_vertex(member, used_vars))
        fn = "create_vertex_with_string" if e.vertex_string else "create_vertex"
        return f"{fn}<{e.op}>(ctx_, " + ', '.join(args) + ")"

    def print_matcher_cond(self, e: Expr, name: str, printer: CodePrinter, vars_declared: Set[str]):
        if e.op == Expr.OP_ANY:
            return
        vertex_info = self.vertex_schema.get(e.op)
        named_range: Optional[Tuple[str, str]] = None
        if vertex_info.is_variadic():
            range_info = vertex_info.get_range()
            range_min_index, range_max_index = vertex_info.get_range_bounds(len(e.members))
            if e.dot3pos is None or range_min_index > e.dot3pos:
                expected_len = range_max_index - range_min_index + 1
                printer.write_line(f"if ({name}->{range_info.name}().size() != {expected_len}) {{ break; }}", e.line)
            elif e.dot3pos == 0 and range_min_index == 0 and len(e.members) == 1 and e.members[0].op == Expr.OP_ANY and e.members[0].name:
                named_range = (e.members[0].name, range_info.name)
            elif e.dot3pos and range_min_index < e.dot3pos:
                expected_len = e.dot3pos - range_min_index + 1
                printer.write_line(f"if ({name}->{range_info.name}().size() < {expected_len}) {{ break; }}", e.line)
        if e.vertex_string:
            printer.write_line(f"if ({name}->get_string() != std::string_view({e.vertex_string})) {{ break; }}", e.line)
        if named_range:
            printer.write_line(f"const auto &{named_range[0]} = {name}->{named_range[1]}();", e.line)
            return
        for i, subexpr in enumerate(e.members):
            arg_info, range_offset = vertex_info.get_arg(i, len(e.members))
            if arg_info.optional:
                printer.write_line(f"if (!{name}->has_{arg_info.name}()) {{ break; }}", subexpr.line)
            arg_expr = f"{name}->{arg_info.name}()" if range_offset is None else f"{name}->{arg_info.name}()[{range_offset}]"
            expr_unwrap_func = self.__unwrap_expr_func(subexpr.op)
            if expr_unwrap_func:
                arg_expr = f"{expr_unwrap_func}({arg_expr})"
            new_name = subexpr.name if subexpr.name else f"{name}{i}_"
            if subexpr.name and subexpr.name in vars_declared:
                printer.write_line(f"if (!is_same({subexpr.name}, {arg_expr})) {{ break; }}", subexpr.line)
            else:
                if subexpr.op == Expr.OP_ANY:
                    if new_name != "_":
                        printer.write_line(f"const auto &{new_name} = {arg_expr};", subexpr.line)
                else:
                    printer.write_line(f"const auto &{new_name} = vertex_cast<{subexpr.op}>({arg_expr});", subexpr.line)
                    printer.write_line(f"if (!{new_name}) {{ break; }}", subexpr.line)
                if subexpr.name and subexpr.name != "_":
                    vars_declared.add(subexpr.name)
            self.print_matcher_cond(subexpr, new_name, printer, vars_declared)

    @staticmethod
    def __is_cachable_op(op: str) -> bool:
        can_cache = {'op_func_call', 'op_int_const', 'op_string'}
        return op in can_cache

    @staticmethod
    def __print_where_cond(cond: str, printer: CodePrinter):
        if not cond:
            return
        printer.write_and_enter_indent(f"if (!({cond})) {{")
        printer.write_line("break;")
        printer.leave_indent_and_write("}")

    @staticmethod
    def __unwrap_expr_func(op: str) -> str:
        if op == "op_string":
            return "VertexUtil::unwrap_string_value"
        if op == "op_int_const":
            return "VertexUtil::unwrap_int_value"
        if op == "op_float_const":
            return "VertexUtil::unwrap_float_value"
        if op == "op_array":
            return "VertexUtil::unwrap_array_value"
        if op == "op_true" or op == "op_false":
            return "VertexUtil::unwrap_bool_value"
        return ""